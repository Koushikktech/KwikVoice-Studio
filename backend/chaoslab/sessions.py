import hashlib
import json
import time
from dataclasses import dataclass, field
from difflib import unified_diff
from uuid import uuid4

from fastapi import HTTPException

from .merchant import ENVIRONMENT, EXAMPLE_PREFIX, LONG_EXAMPLE, SHORT_EXAMPLE, WORD_TARGET, lint, word_count

SESSION_TTL = 4 * 60 * 60
MAX_SESSIONS = 256


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid4().hex)
    touched: float = field(default_factory=time.monotonic)
    compiled: dict = field(default_factory=dict)
    revision: str = ""
    base_revision: str = ""
    base_template: str | None = None
    engine: str | None = None
    results: dict = field(default_factory=dict)
    before: dict | None = None
    pending_ids: set = field(default_factory=set)
    patch: dict | None = None
    running: bool = False

    def install(self, compiled: dict, input_identity: str) -> None:
        self.base_revision = input_identity
        revision = fingerprint([input_identity, compiled["prompt"]])
        if self.revision != revision:
            self.results = {}
            self.before = None
            self.pending_ids = set()
            self.patch = None
        self.revision = revision
        self.compiled = compiled

    def generate_patch(self, persona_id: str | None, source: str | None) -> dict:
        if source is not None and source != self.compiled["prompt"]:
            raise HTTPException(409, "Compile the current prompt before proposing an edit.")
        current = self.compiled["prompt"]
        failures = self.failures(persona_id)
        if not failures:
            raise HTTPException(422, "Run the shopper scenarios and select a failed check.")
        for evidence in failures:
            original = evidence["utterance"]
            if not original:
                continue
            line = f"{EXAMPLE_PREFIX}{original}"
            if current.splitlines().count(line) != 1:
                continue
            reason = "Replace raw checkout tokens in the spoken example."
            if evidence["label"] == "Turn length":
                reason = f"Shorten the {word_count(original)}-word example to fit the {WORD_TARGET}-word limit."
                if original == LONG_EXAMPLE:
                    new_line = EXAMPLE_PREFIX + SHORT_EXAMPLE
                else:
                    # Preserve the first complete sentence when it fits the turn limit.
                    first = original.partition(". ")[0].rstrip(".") + "."
                    if word_count(first) > WORD_TARGET:
                        continue
                    new_line = EXAMPLE_PREFIX + first
            elif evidence["label"] == "Spoken data":
                new_line = lint(line)["fixed_prompt"].rstrip()
            else:
                continue
            if new_line == line:
                continue
            replacement = "\n".join(new_line if entry == line else entry for entry in current.split("\n"))
            patch = self.stage_edit(replacement, reason, evidence)
            if original == LONG_EXAMPLE and new_line == EXAMPLE_PREFIX + SHORT_EXAMPLE:
                base = self.base_template or ENVIRONMENT.loader.get_source(ENVIRONMENT, "base.jinja")[0]
                if line in base.splitlines():
                    target = base.replace(line, new_line, 1)
                    patch["base_template"] = target
                    patch["rendered_diff"] = patch["diff"]
                    patch["diff"] = "".join(unified_diff(
                        base.splitlines(keepends=True), target.splitlines(keepends=True),
                        fromfile="a/templates/base.jinja", tofile="b/templates/base.jinja",
                    ))
            return patch
        raise HTTPException(422, "The failed turn needs a model-assisted edit or a manual prompt change.")

    def failures(self, persona_id: str | None) -> list[dict]:
        failures = []
        for result in self.results.values():
            if result["passed"] is not False or (persona_id and result["persona_id"] != persona_id):
                continue
            turns = {t["turn"]: t["text"] for t in result["transcript"] if t["speaker"] == "agent"}
            for check in result["checks"]:
                if not check["passed"]:
                    failures.append({**check, "persona_id": result["persona_id"],
                                     "utterance": turns.get(check["turn"], "")})
        return failures

    def stage_edit(self, replacement: str, reason: str, evidence: dict) -> dict:
        current = self.compiled["prompt"]
        diff = "".join(unified_diff(
            current.splitlines(keepends=True), replacement.splitlines(keepends=True),
            fromfile="active prompt", tofile="proposed prompt",
        ))
        self.patch = {
            "id": uuid4().hex, "revision": self.revision, "prompt": replacement, "diff": diff,
            "reason": reason, "evidence": evidence,
        }
        return self.patch

    def apply_patch(self, patch_id: str) -> None:
        patch = self.patch
        if self.before is not None and self.before["patch_id"] == patch_id:
            return
        if not patch or patch["id"] != patch_id or patch["revision"] != self.revision:
            raise HTTPException(409, "Propose a new edit against the current prompt.")
        self.before = {
            "patch_id": patch_id, "score": score(self.results),
            "failed_ids": sorted(key for key, value in self.results.items() if value["passed"] is False),
        }
        self.pending_ids = set(self.before["failed_ids"])
        self.base_template = patch.get("base_template", self.base_template)
        prompt = patch["prompt"]
        self.compiled = {**self.compiled, "prompt": prompt, "lint": lint(prompt)}
        self.revision = fingerprint([self.base_revision, prompt])
        self.patch = None

    def snapshot(self) -> dict:
        return {"session_id": self.id, "revision": self.revision, **self.compiled,
                "results": self.results, "score": score(self.results), "before": self.before,
                "pending_ids": sorted(self.pending_ids)}


def fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def score(results: dict) -> dict:
    return {
        "passed": sum(value["passed"] is True for value in results.values()),
        "failed": sum(value["passed"] is False for value in results.values()),
        "errors": sum(value["passed"] is None for value in results.values()),
        "total": len(results),
    }


sessions: dict[str, Session] = {}


def open_session(session_id: str | None = None, revision: str | None = None) -> Session:
    now = time.monotonic()
    for key in list(sessions):
        session = sessions[key]
        if not session.running and now - session.touched > SESSION_TTL:
            del sessions[key]
    if session_id:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "This session expired. Recompile to start a new one.")
        if revision is not None and revision != session.revision:
            raise HTTPException(409, "The prompt changed. Use the current session revision.")
    else:
        if len(sessions) >= MAX_SESSIONS:
            oldest = min((session for session in sessions.values() if not session.running),
                         key=lambda session: session.touched, default=None)
            if oldest is None:
                raise HTTPException(503, "The backend is busy. Try again shortly.")
            del sessions[oldest.id]
        session = Session()
        sessions[session.id] = session
    session.touched = now
    return session
