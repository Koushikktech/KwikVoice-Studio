"""Export real fixture QA evidence for the static reviewer demo."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from chaoslab.main import app
from chaoslab.merchant import PRESETS

root = Path(__file__).resolve().parents[1]


def post(client, url, data):
    response = client.post(url, json=data)
    response.raise_for_status()
    return response


def completed_run(client, payload):
    response = post(client, "/api/swarm/run", payload)
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "complete"
    return events[-1]


def identity(session):
    return {key: session[key] for key in ("session_id", "revision")}


def main():
    recording = json.loads((root / "frontend/public/recordings/dermpure-call.json").read_text())
    with TestClient(app) as client:
        session = post(client, "/api/compile", PRESETS[0]).json()
        before = completed_run(client, identity(session))
        patch = post(client, "/api/patch/generate", identity(session)).json()
        applied = post(client, "/api/patch/apply", dict(identity(session), patch_id=patch["id"])).json()
        after = completed_run(client, dict(identity(applied), failed_only=True))

    def interruption(run):
        return next(turn["text"] for turn in run["results"]["interrupt"]["transcript"] if turn["speaker"] == "agent")

    data = {
        "recording": {key: recording[key] for key in ("lines", "events")},
        "prices": {key: session["context"]["price"][key] for key in ("cod", "upi", "savings")},
        "fixture": {
            "before": {"passed": before["score"]["passed"], "reply": interruption(before)},
            "after": {"passed": after["score"]["passed"], "reply": interruption(after)},
            "total": after["score"]["total"],
        },
    }
    (root / "demo/evidence.js").write_text("export default " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n")


if __name__ == "__main__":
    main()
