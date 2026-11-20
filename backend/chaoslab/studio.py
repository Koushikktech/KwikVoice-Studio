import asyncio
import json
import logging
import re
import time
from secrets import compare_digest

from fastapi import WebSocket, WebSocketDisconnect
from google.genai import types
from websockets.exceptions import ConnectionClosed

from . import config
from .consent import YES, agreed, normalized, offered_action
from .commerce import callback_call, checkout_call, cod_call, mock_tool, tool_declarations
from .merchant import model_prompt, word_count

logger = logging.getLogger(__name__)


def replay_turns(context: dict) -> list[tuple[str, str, dict | None]]:
    price = context["spoken"]
    fee = price["cod_fee"].replace("rupees", "rupee")
    return [
        ("COD mein extra charge kyun hai?",
         f"Cash on delivery costs {price['cod']}, including a {fee} fee.", None),
        ("UPI se kitna hoga?", f"UPI par {price['upi']}. Aap {price['savings']} bachayenge.", None),
        ("Haan, UPI link bhej do.", "Theek hai, aapka mock checkout link bhej diya.", checkout_call(context)),
    ]


def text_reply(text: str, context: dict, offer: str | None = None) -> tuple[str, dict | None]:
    if agreed("send_checkout_link", text, offer):
        return "Your mock checkout link is ready.", checkout_call(context)
    if agreed("confirm_cod_order", text, offer):
        return "Your mock COD order is confirmed.", cod_call(context)
    if agreed("schedule_callback", text, offer):
        return "I've queued a mock callback.", callback_call(context)
    price = context["spoken"]
    message = text.casefold()
    if normalized(message) in YES:
        return "What would you like help with?", None
    if re.fullmatch(r"(?:no(?: thanks)?|not now|no thank you|maybe later|leave it|nahi|later)[.! ]*", message):
        return "Okay, we can leave it here.", None
    if re.fullmatch(r"(?:thanks|thank you|bye|goodbye)[.! ]*", message):
        return "Thank you. Goodbye.", None
    if re.search(r"\b(?:item|product)s? in my cart|what(?:'s| is) in my cart", message):
        return "Your cart contains " + ", ".join(context["products"]) + ".", None
    if context["coupon"].casefold() in message or "coupon" in message:
        return "I can't verify that coupon. I can share the approved UPI total.", None
    if re.search(r"\b(off|discount|percent)\b|%", message):
        return f"I can offer up to {context['spoken_discount']} on UPI.", None
    if re.search(r"\b(?:save|saving|savings|bach)\b", message):
        return f"You would save {price['savings']} with UPI.", None
    if re.search(r"\bupi\b", message):
        return f"The UPI total is {price['upi']}.", None
    if re.search(r"\b(fee|extra|charge)\b", message):
        return f"The COD fee is {price['cod_fee']}.", None
    if re.search(r"\b(cod|cash on delivery)\b", message):
        return f"Your COD total is {price['cod']}.", None
    for fact in context["faq"]:
        if message.rstrip("? .") == fact["question"].casefold().rstrip("? ."):
            return fact["answer"], None
    return "I don't have that detail. Would you like a callback?", None


async def local_call(socket: WebSocket, mode: str, context: dict) -> None:
    replay = replay_turns(context) if mode == "replay" else []
    await socket.send_json({"type": "ready", "mode": mode})
    turn = 0
    offer = None
    while True:
        packet = await socket.receive_json()
        if not isinstance(packet, dict):
            continue
        if packet.get("type") == "stop":
            return
        if mode == "replay":
            if packet.get("type") != "next":
                continue
            if turn == len(replay):
                await socket.send_json({"type": "done"})
                return
            text, reply, action = replay[turn]
        else:
            text = packet.get("text")
            if packet.get("type") != "text" or not isinstance(text, str) or not text.strip():
                continue
            if len(text) > 500:
                await socket.send_json({"type": "notice", "message": "Keep each text turn under 500 characters."})
                continue
            text = text.strip()
            reply, action = text_reply(text, context, offer)
        turn += 1
        await socket.send_json({"type": "transcript", "speaker": "shopper", "text": text,
                                "turn": turn, "final": True})
        if action:
            outcome = mock_tool(action["name"], action["args"], context, text, offer)
            await socket.send_json({"type": "tool", "turn": turn, **outcome})
            if not outcome["ok"]:
                reply = "I couldn't complete that mock action."
        offer = offered_action(reply)
        await socket.send_json({"type": "transcript", "speaker": "agent", "text": reply,
                                "turn": turn, "words": word_count(reply), "final": True})


def merge_transcript(previous: str, update: str) -> str:
    # Gemini can send incremental fragments and cumulative revisions.
    if update.startswith(previous) or not previous:
        return update
    if previous.endswith(update):
        return previous
    return previous + update


async def live_call(socket: WebSocket, prompt: str, context: dict) -> None:
    declarations = tool_declarations()
    # Gemini 3.8 can speak an asynchronous tool result after the action turn ends.
    async_tools = config.LIVE_MODEL.removeprefix("models/").startswith("gemini-3.8-live")
    if async_tools:
        for declaration in declarations:
            declaration["behavior"] = "NON_BLOCKING"
    options = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=model_prompt(prompt),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        ),
        tools=[types.Tool(function_declarations=declarations)],
    )
    async with config.gemini_client().aio.live.connect(model=config.LIVE_MODEL, config=options) as live:
        await socket.send_json({"type": "ready", "mode": "live", "model": config.LIVE_MODEL})
        first_audio = None
        turn = 1
        caller = ""
        agent = ""
        call_started = time.monotonic()
        last_voiced_at = None
        offer = None
        completed_calls: dict[str, dict] = {}

        async def upstream() -> None:
            nonlocal last_voiced_at
            while True:
                packet = await socket.receive()
                if packet["type"] == "websocket.disconnect":
                    return
                if audio := packet.get("bytes"):
                    if len(audio) % 2 == 0 and len(audio) <= 6400:
                        samples = memoryview(audio).cast("h")[::8]
                        if samples and sum(s * s for s in samples) / len(samples) > 220 ** 2:
                            last_voiced_at = time.monotonic()
                        await live.send_realtime_input(audio=types.Blob(
                            data=audio, mime_type="audio/pcm;rate=16000",
                        ))
                elif signal := packet.get("text"):
                    try:
                        if json.loads(signal) == {"type": "stop"}:
                            await live.send_realtime_input(audio_stream_end=True)
                            return
                    except json.JSONDecodeError:
                        continue

        async def transcript(speaker: str, text: str, final: bool) -> None:
            if not text.strip():
                return
            event = {"type": "transcript", "speaker": speaker, "text": text.strip(),
                     "turn": turn, "final": final}
            if speaker == "agent":
                event["words"] = word_count(text)
            await socket.send_json(event)

        async def downstream() -> None:
            nonlocal first_audio, turn, caller, agent, offer
            while True:
                async for message in live.receive():
                    content = message.server_content
                    if content:
                        if content.input_transcription and content.input_transcription.text:
                            caller = merge_transcript(caller, content.input_transcription.text)
                            await transcript("shopper", caller, bool(content.input_transcription.finished))
                        if content.interrupted:
                            await socket.send_json({"type": "interrupted", "turn": turn})
                            await transcript("agent", agent, True)
                            agent = ""
                            offer = None
                        if content.output_transcription and content.output_transcription.text:
                            agent = merge_transcript(agent, content.output_transcription.text)
                            await transcript("agent", agent, bool(content.output_transcription.finished))
                        if message.data and not content.interrupted:
                            if first_audio is None:
                                first_audio = round((time.monotonic() - (last_voiced_at or call_started)) * 1000)
                                await socket.send_json({
                                    "type": "first_audio", "ms": first_audio,
                                    "basis": "last voiced input frame" if last_voiced_at else "session start",
                                })
                            await socket.send_bytes(message.data)
                        if content.turn_complete:
                            await transcript("shopper", caller, True)
                            await transcript("agent", agent, True)
                            offer = offered_action(agent) if not content.interrupted else None
                            turn += 1
                            caller = agent = ""

                    if message.tool_call:
                        responses = []
                        for call in message.tool_call.function_calls or []:
                            outcome = completed_calls.get(call.id or "")
                            if outcome is None:
                                outcome = mock_tool(call.name or "", call.args or {}, context, caller, offer)
                                if call.id:
                                    completed_calls[call.id] = outcome
                                await socket.send_json({"type": "tool", "turn": turn, **outcome})
                            responses.append(types.FunctionResponse(
                                id=call.id, name=call.name,
                                scheduling=types.FunctionResponseScheduling.WHEN_IDLE if async_tools else None,
                                response={**{key: value for key, value in outcome.items() if key in {"ok", "message", "card"}},
                                          "next": "Tell the caller the result briefly in their language."},
                            ))
                        if responses:
                            await live.send_tool_response(function_responses=responses)
                    if message.tool_call_cancellation:
                        await socket.send_json({"type": "notice", "message": "Gemini canceled a pending mock action."})
                    if message.go_away:
                        await socket.send_json({"type": "notice", "message": "Gemini asked to end this session."})
                        return

        tasks = [asyncio.create_task(task()) for task in (upstream, downstream)]
        try:
            done, _ = await asyncio.wait(tasks, timeout=600, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            await socket.send_json({"type": "done"})
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def allowed_origin(origin: str | None) -> bool:
    return origin is None or any(compare_digest(origin, candidate) for candidate in config.ORIGINS)


async def run_studio(socket: WebSocket, mode: str, compiled: dict) -> None:
    try:
        if mode == "live":
            if not config.gemini_available():
                await socket.send_json({"type": "error", "message": "Set GEMINI_API_KEY on the backend or choose replay or text."})
            else:
                await live_call(socket, compiled["prompt"], compiled["context"])
        else:
            await local_call(socket, mode, compiled["context"])
        await socket.close()
    except WebSocketDisconnect:
        return
    except ConnectionClosed as error:
        code = error.rcvd.code if error.rcvd else None
        logger.info("Gemini Live socket closed with code %s", code)
        try:
            if code not in (1000, 1001):
                await socket.send_json({
                    "type": "notice",
                    "message": "Gemini closed the audio connection. Start a new call to continue.",
                })
            await socket.send_json({"type": "done"})
            await socket.close()
        except (RuntimeError, WebSocketDisconnect):
            return
    except Exception as error:
        logger.warning("Studio %s ended with %s", mode, type(error).__name__)
        try:
            await socket.send_json({
                "type": "error",
                "message": "The studio connection ended early. Check the backend and model settings, or use replay or text.",
            })
            await socket.close(code=1011)
        except (RuntimeError, WebSocketDisconnect):
            return
