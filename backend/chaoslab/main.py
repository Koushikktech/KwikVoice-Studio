import asyncio
import json
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import Field, StringConstraints

from . import config
from .merchant import PRESETS, InputModel, MerchantInput, compile_merchant, lint
from .repair import propose_edit
from .qa import PERSONAS, PERSONA_BY_ID, Engine, build_graph, run_persona
from .sessions import fingerprint, open_session
from .studio import allowed_origin, run_studio

Prompt = Annotated[str, StringConstraints(min_length=1, max_length=24000)]
SessionId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]{32}$")]
Revision = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]{20}$")]
Mode = Literal["replay", "text", "live"]

app = FastAPI(title="KwikVoice ChaosLab")
app.add_middleware(
    CORSMiddleware, allow_origins=sorted(config.ORIGINS),
    allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
)


class CompileRequest(MerchantInput):
    session_id: SessionId | None = None
    prompt: Prompt | None = None


class LintRequest(InputModel):
    prompt: Annotated[str, StringConstraints(max_length=24000)]


class ActiveSession(InputModel):
    session_id: SessionId
    revision: Revision


class SwarmRequest(ActiveSession):
    engine: Engine = "fixture"
    persona_ids: list[str] | None = Field(default=None, min_length=1, max_length=5)
    failed_only: bool = False


class PatchRequest(ActiveSession):
    persona_id: str | None = None
    source: Prompt | None = None


class ApplyRequest(ActiveSession):
    patch_id: SessionId


@app.get("/api/health")
async def health():
    return {"ok": True, "gemini_available": config.gemini_available()}


@app.get("/api/presets")
async def presets():
    return {
        "presets": PRESETS, "personas": [asdict(persona) for persona in PERSONAS],
        "gemini": {"available": config.gemini_available(), "text_model": config.TEXT_MODEL,
                   "judge_model": config.JUDGE_MODEL, "live_model": config.LIVE_MODEL},
    }


@app.post("/api/compile")
async def compile_prompt(request: CompileRequest):
    data = request.model_dump(mode="json", exclude={"prompt", "session_id"})
    session = open_session(request.session_id)
    try:
        compiled = compile_merchant(MerchantInput.model_validate(data), session.base_template)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if request.prompt is not None:
        compiled.update(prompt=request.prompt, lint=lint(request.prompt))
    session.install(compiled, fingerprint(data))
    return session.snapshot()


@app.post("/api/lint")
async def lint_prompt(request: LintRequest):
    return lint(request.prompt)


def require_ready(compiled: dict) -> None:
    if any(issue["code"] == "unresolved_variable" for issue in compiled["lint"]["diagnostics"]):
        raise HTTPException(422, "Resolve the template variables before running the prompt.")
    if not compiled["prompt"].strip():
        raise HTTPException(422, "Enter an active prompt before running.")


@app.post("/api/swarm/run")
async def swarm(request: SwarmRequest):
    session = open_session(request.session_id, request.revision)
    if session.running:
        raise HTTPException(409, "A QA run is already in progress for this session.")
    require_ready(session.compiled)
    if request.engine == "gemini" and not config.gemini_available():
        raise HTTPException(422, "Set GEMINI_API_KEY or choose the fixture engine.")
    if request.failed_only:
        if request.persona_ids or not session.pending_ids or session.engine != request.engine:
            raise HTTPException(409, "Apply a patch and rerun its failed shoppers with the same engine.")
        selected = [p.id for p in PERSONAS if p.id in session.pending_ids]
    else:
        selected = request.persona_ids or list(PERSONA_BY_ID)
    if len(set(selected)) != len(selected) or any(key not in PERSONA_BY_ID for key in selected):
        raise HTTPException(422, "Choose distinct fixed QA personas.")
    keep_results = session.engine == request.engine
    compiled = session.compiled
    session.running = True

    async def stream():
        queue: asyncio.Queue = asyncio.Queue()
        graph = build_graph(queue.put)

        async def collect():
            try:
                verdicts = await asyncio.gather(*(run_persona({
                    "persona_id": key, "engine": request.engine, "prompt": compiled["prompt"],
                    "context": compiled["context"],
                }, queue.put, graph) for key in selected))
                if session.revision != request.revision:
                    await queue.put({"type": "error", "message": "Inputs changed during this run. Run QA again."})
                    return
                if not keep_results or (not request.failed_only and not request.persona_ids):
                    session.results = {}
                if not keep_results:
                    session.before = None
                    session.pending_ids.clear()
                session.engine = request.engine
                session.results.update({result["persona_id"]: result for result in verdicts})
                session.pending_ids.difference_update(
                    result["persona_id"] for result in verdicts if result["passed"] is not None
                )
                session.patch = None
                await queue.put({"type": "complete", "ran_ids": selected, "engine": request.engine,
                                 **session.snapshot()})
            except Exception:
                await queue.put({"type": "error", "message": "QA stopped before it finished. Run the scenario again."})
            finally:
                await queue.put(None)

        worker = asyncio.create_task(collect())
        try:
            yield sse({"type": "start", "persona_ids": selected, "engine": request.engine})
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=12)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    break
                yield sse(event)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            session.running = False

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/api/patch/generate")
async def generate_patch(request: PatchRequest):
    session = open_session(request.session_id, request.revision)
    if session.running:
        raise HTTPException(409, "Wait for QA to finish before proposing a patch.")
    return await propose_edit(session, request.persona_id, request.source)


@app.post("/api/patch/apply")
async def apply_patch(request: ApplyRequest):
    session = open_session(request.session_id, request.revision)
    if session.running:
        raise HTTPException(409, "Wait for QA to finish before applying a patch.")
    session.apply_patch(request.patch_id)
    return session.snapshot()


@app.websocket("/ws/live-call")
async def studio(socket: WebSocket, session_id: SessionId, revision: Revision, mode: Mode = "replay"):
    if not allowed_origin(socket.headers.get("origin")):
        await socket.close(code=1008)
        return
    await socket.accept()
    try:
        session = open_session(session_id, revision)
        require_ready(session.compiled)
    except HTTPException as error:
        await socket.send_json({"type": "error", "message": error.detail})
        await socket.close(code=1008)
        return
    await run_studio(socket, mode, session.compiled)
