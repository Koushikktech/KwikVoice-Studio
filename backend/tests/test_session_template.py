import json

from fastapi.testclient import TestClient

from chaoslab.main import app
from chaoslab.merchant import LONG_EXAMPLE, PRESETS, SHORT_EXAMPLE


def snapshot_fields(snapshot):
    return {key: snapshot[key] for key in ("session_id", "revision")}


def last_event(response):
    response.raise_for_status()
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "complete"
    return events[-1]


def test_reviewed_brevity_patch_applies_to_session_master_only():
    with TestClient(app) as client:
        compiled = client.post("/api/compile", json=PRESETS[0]).json()
        active = snapshot_fields(compiled)
        baseline = last_event(client.post("/api/swarm/run", json=active))
        assert baseline["score"]["passed"] == 4
        patch = client.post("/api/patch/generate", json=active).json()
        assert "templates/base.jinja" in patch["diff"]
        assert LONG_EXAMPLE in patch["evidence"]["utterance"]
        applied = client.post("/api/patch/apply", json={**active, "patch_id": patch["id"]}).json()
        rerun = last_event(client.post("/api/swarm/run", json={**snapshot_fields(applied), "failed_only": True}))
        assert rerun["ran_ids"] == ["interrupt"]
        assert rerun["score"]["passed"] == 5
        other = client.post("/api/compile", json={**PRESETS[1], "session_id": active["session_id"]}).json()
        assert SHORT_EXAMPLE in other["prompt"] and LONG_EXAMPLE not in other["prompt"]
        fresh = client.post("/api/compile", json=PRESETS[1]).json()
        assert LONG_EXAMPLE in fresh["prompt"]
