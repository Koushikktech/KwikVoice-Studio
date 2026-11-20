import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from chaoslab import config
from chaoslab.commerce import checkout_call, mock_tool
from chaoslab.main import app
from chaoslab.merchant import PRESETS, MerchantInput, compile_merchant


@pytest.fixture
def client():
    with TestClient(app) as instance:
        yield instance


def compile_cart(client, index=0, **extra):
    response = client.post("/api/compile", json={**deepcopy(PRESETS[index]), **extra})
    response.raise_for_status()
    return response.json()


def active(compiled):
    return {key: compiled[key] for key in ["session_id", "revision"]}


def events(response):
    response.raise_for_status()
    assert response.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.mark.parametrize("flow", ["cart-recovery", "cod-confirmation"])
@pytest.mark.parametrize("preset", range(3))
def test_all_cart_flow_combinations(client, flow, preset):
    compiled = compile_cart(client, preset, flow=flow)
    assert compiled["context"]["flow"] == flow
    assert compiled["context"]["cart_id"] == PRESETS[preset]["cart"]["id"]
    assert compiled["transformations"]
    assert [issue["code"] for issue in compiled["lint"]["diagnostics"]] == ["monologue"]


def test_merchant_prices(client):
    assert compile_cart(client)["context"]["price"] == {
        "subtotal": "699.00", "cod_fee": "50.00", "cod": "749.00", "upi": "629.00", "savings": "120.00",
    }
    retain_fee = compile_cart(client, 2)["context"]
    assert retain_fee["waives_fee"] is False
    assert retain_fee["price"]["upi"] == "698.10"
    assert retain_fee["price"]["savings"] == "34.90"


def test_parallel_sse_and_stale_results(client):
    original = compile_cart(client)
    result = events(client.post("/api/swarm/run", json=active(original)))
    assert result[0]["type"] == "start"
    first_agent = next(index for index, event in enumerate(result) if event.get("speaker") == "agent")
    assert len({event["persona_id"] for event in result[:first_agent] if event["type"] == "turn"}) == 5
    assert sum(event["type"] == "verdict" for event in result) == 5
    assert result[-1]["score"] == {"passed": 4, "failed": 1, "errors": 0, "total": 5}
    failed = result[-1]["results"]["interrupt"]
    assert next(check for check in failed["checks"] if not check["passed"])["turn"] == 1
    assert next(turn["words"] for turn in failed["transcript"] if turn["speaker"] == "agent") == 26
    revised = compile_cart(client, session_id=original["session_id"], prompt=original["prompt"] + "\nSpeak plainly.")
    assert revised["results"] == {}
    assert revised["revision"] != original["revision"]
    assert client.post("/api/swarm/run", json=active(original)).status_code == 409


def test_unresolved_prompt_and_offline_engine(client, monkeypatch):
    monkeypatch.setattr(config, "gemini_available", lambda: False)
    unresolved = compile_cart(client, prompt="Say hello to {{ undefined_name }}.")
    assert client.post("/api/swarm/run", json=active(unresolved)).status_code == 422
    valid = compile_cart(client)
    response = client.post("/api/swarm/run", json={**active(valid), "engine": "gemini"})
    assert response.status_code == 422
    assert "GEMINI_API_KEY" in response.json()["detail"]


@pytest.mark.parametrize("changes,consent", [
    ({"discount_percent": 25}, "Yes, send me the UPI link."),
    ({"amount": "628.00"}, "Yes, send me the UPI link."),
    ({"cart_id": "other-cart"}, "Yes, send me the UPI link."),
    ({"coupon": "FRESH20"}, "Yes, send me the UPI link."),
    ({}, "No, don't send the UPI link."),
    ({}, "What is the UPI price?"),
])
def test_checkout_guard_rejects_unsafe_arguments_or_absent_agreement(changes, consent):
    ctx = compile_merchant(MerchantInput.model_validate(PRESETS[0]))["context"]
    call = checkout_call(ctx)
    outcome = mock_tool(call["name"], {**call["args"], **changes}, ctx, consent)
    assert not outcome["ok"]
    assert "card" not in outcome


def test_checkout_tool_accepts_an_aggregate_cart_total_above_the_item_limit():
    merchant = deepcopy(PRESETS[0])
    merchant["cart"]["items"][0].update(price="100000.00", quantity=20)
    ctx = compile_merchant(MerchantInput.model_validate(merchant))["context"]
    call = checkout_call(ctx)
    outcome = mock_tool(call["name"], call["args"], ctx, "Yes, send me the UPI link.")
    assert outcome["ok"]
    assert outcome["card"]["amount"] == "1800000.00"


def ws_url(compiled, mode):
    return f"/ws/live-call?session_id={compiled['session_id']}&revision={compiled['revision']}&mode={mode}"


def test_replay_emits_checkout_from_the_current_merchant(client):
    compiled = compile_cart(client, 2)
    with client.websocket_connect(ws_url(compiled, "replay")) as socket:
        assert socket.receive_json()["mode"] == "replay"
        for turn in range(1, 4):
            socket.send_json({"type": "next"})
            assert socket.receive_json()["speaker"] == "shopper"
            if turn == 3:
                tool = socket.receive_json()
                assert tool["ok"] and tool["card"]["amount"] == compiled["context"]["price"]["upi"]
                assert tool["card"]["cart_id"] == compiled["context"]["cart_id"]
            assert socket.receive_json()["speaker"] == "agent"
        socket.send_json({"type": "next"})
        assert socket.receive_json()["type"] == "done"


def test_text_mode_requires_explicit_cod_and_callback_consent(client):
    with client.websocket_connect(ws_url(compile_cart(client), "text")) as socket:
        assert socket.receive_json() == {"type": "ready", "mode": "text"}
        for text, action in [
            ("What is my COD total?", None),
            ("Please confirm my COD order.", "confirm_cod_order"),
            ("Please call me back.", "schedule_callback"),
        ]:
            socket.send_json({"type": "text", "text": text})
            assert socket.receive_json()["speaker"] == "shopper"
            if action:
                tool = socket.receive_json()
                assert tool["type"] == "tool" and tool["name"] == action and tool["ok"]
            assert socket.receive_json()["speaker"] == "agent"


def test_live_bridge_sends_pcm_checks_tool_response_and_signals_barge_in(client, monkeypatch):
    compiled = compile_cart(client)
    pcm = b"\x00\x10" * 320
    outgoing = b"\x0f\x00" * 480
    observations = []

    class LiveDouble:
        def __init__(self):
            self.queue = asyncio.Queue()

        async def send_realtime_input(self, **data):
            if blob := data.get("audio"):
                assert blob.data == pcm
                assert blob.mime_type == "audio/pcm;rate=16000"
                await self.queue.put(types.LiveServerMessage(server_content=types.LiveServerContent(
                    input_transcription=types.Transcription(text="Yes, send me the UPI link.", finished=True),
                    model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(
                        data=outgoing, mime_type="audio/pcm;rate=24000",
                    ))]),
                )))
                call = checkout_call(compiled["context"])
                await self.queue.put(types.LiveServerMessage(tool_call=types.LiveServerToolCall(
                    function_calls=[types.FunctionCall(id="call-1", name=call["name"], args=call["args"])],
                )))

        async def send_tool_response(self, function_responses):
            response = function_responses[0]
            assert response.scheduling == types.FunctionResponseScheduling.WHEN_IDLE
            observations.append(response)
            await self.queue.put(types.LiveServerMessage(
                server_content=types.LiveServerContent(interrupted=True, turn_complete=True),
            ))

        async def receive(self):
            while message := await self.queue.get():
                yield message
                if message.server_content and message.server_content.turn_complete:
                    break

    @asynccontextmanager
    async def connect(model, config):
        assert model
        assert config.tools[0].function_declarations[0].behavior == types.Behavior.NON_BLOCKING
        assert config.response_modalities == [types.Modality.AUDIO]
        assert config.realtime_input_config.activity_handling == types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
        yield LiveDouble()

    monkeypatch.setattr(config, "gemini_available", lambda: True)
    monkeypatch.setattr(config, "gemini_client", lambda: SimpleNamespace(aio=SimpleNamespace(
        live=SimpleNamespace(connect=connect),
    )))
    with client.websocket_connect(ws_url(compiled, "live")) as socket:
        assert socket.receive_json()["mode"] == "live"
        socket.send_bytes(pcm)
        assert socket.receive_json()["speaker"] == "shopper"
        assert socket.receive_json()["type"] == "first_audio"
        assert socket.receive_bytes() == outgoing
        result = socket.receive_json()
        assert result["ok"] and result["card"]["amount"] == "629.00"
        assert socket.receive_json()["type"] == "interrupted"
        assert observations[0].id == "call-1"
        assert observations[0].response["ok"] is True


def test_text_offer_expires_on_topic_change(client):
    with client.websocket_connect(ws_url(compile_cart(client), "text")) as socket:
        assert socket.receive_json()["type"] == "ready"
        for message, expected_action in [
            ("Do you have a refill plan?", None),
            ("What is my COD total?", None),
            ("yes", None),
            ("Do you have a refill plan?", None),
            ("yes", "schedule_callback"),
        ]:
            socket.send_json({"type": "text", "text": message})
            assert socket.receive_json()["speaker"] == "shopper"
            if expected_action:
                outcome = socket.receive_json()
                assert outcome["name"] == expected_action and outcome["ok"]
            assert socket.receive_json()["speaker"] == "agent"
