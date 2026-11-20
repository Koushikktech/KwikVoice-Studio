import asyncio
import os
import time
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash-lite")
JUDGE_MODEL = os.getenv("GEMINI_JUDGE_MODEL") or TEXT_MODEL
LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")
ORIGINS = {
    origin.strip() for origin in os.getenv(
        "WORKBENCH_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",") if origin.strip()
}


def gemini_available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


@lru_cache(maxsize=1)
def gemini_client() -> genai.Client:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise ValueError("Set GEMINI_API_KEY to use Gemini modes.")
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60_000))

def text_thinking(model: str) -> types.ThinkingConfig | None:
    if model.startswith("gemini-3.5-flash-lite"):
        return types.ThinkingConfig(thinking_level="MINIMAL")
    if model.startswith("gemini-3"):
        return types.ThinkingConfig(thinking_level="LOW")
    return None


# Reserve request slots across concurrent shoppers. Free-tier limits are per model.
_request_times: dict[str, deque[float]] = defaultdict(deque)
TEXT_REQUESTS_PER_MINUTE = max(1, int(os.getenv("GEMINI_TEXT_RPM", "14")))


async def reserve_text_request(model: str) -> None:
    times = _request_times[model]
    while True:
        now = time.monotonic()
        while times and now - times[0] >= 61:
            times.popleft()
        if len(times) < TEXT_REQUESTS_PER_MINUTE:
            times.append(now)
            return
        await asyncio.sleep(max(0, 61 - (now - times[0])))


async def generate_text(*, model: str, contents, config: types.GenerateContentConfig):
    for attempt in range(2):
        await reserve_text_request(model)
        try:
            return await gemini_client().aio.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as exc:
            if attempt or exc.code not in (429, 503, 504):
                raise
            if exc.code == 429:
                details = (exc.details or {}).get("error", {}).get("details", []) if isinstance(exc.details, dict) else []
                retry = next((d.get("retryDelay") for d in details if "retryDelay" in d), None)
                if not retry or not retry.endswith("s") or not retry[:-1].replace(".", "", 1).isdigit():
                    raise
                delay = float(retry[:-1]) + 1
                if delay > 65:
                    raise
            else:
                delay = 2
            await asyncio.sleep(delay)
