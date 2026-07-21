import base64

import httpx
from app.core.config import settings

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# Vision-capable model for Groq. Groq's non-vision default (llama-3.3-70b-versatile)
# cannot take image input, so this is intentionally a separate constant rather
# than reusing settings.GROQ_MODEL. Override via GROQ_VISION_MODEL if Groq
# rotates the model id (they've deprecated vision preview models before).
GROQ_VISION_MODEL_DEFAULT = "qwen/qwen3.6-27b"


async def _ask_groq(prompt: str, system: str | None = None) -> str:
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            json={"model": settings.GROQ_MODEL, "messages": messages, "temperature": 0.2},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _ask_anthropic(prompt: str, system: str | None = None) -> str:
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    body = {
        "model": settings.ANTHROPIC_MODEL,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


async def ask_llm(prompt: str, system: str | None = None) -> str:
    """Single entry point every router should call. Swaps provider based on
    LLM_PROVIDER env var - nothing else in the app needs to know or care."""
    if settings.LLM_PROVIDER == "anthropic":
        return await _ask_anthropic(prompt, system)
    return await _ask_groq(prompt, system)


async def _ask_groq_vision(image_bytes: bytes, mime_type: str, prompt: str, system: str | None = None) -> str:
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set")

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64}"
    vision_model = getattr(settings, "GROQ_VISION_MODEL", None) or GROQ_VISION_MODEL_DEFAULT

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    })

    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            json={"model": vision_model, "messages": messages, "temperature": 0.2},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _ask_anthropic_vision(image_bytes: bytes, mime_type: str, prompt: str, system: str | None = None) -> str:
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    b64 = base64.b64encode(image_bytes).decode("utf-8")

    body = {
        "model": settings.ANTHROPIC_MODEL,  # claude-sonnet-4-6 is already vision-capable
        "max_tokens": 1024,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    }
    if system:
        body["system"] = system

    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


async def ask_llm_vision(image_bytes: bytes, mime_type: str, prompt: str, system: str | None = None) -> str:
    """Vision counterpart to ask_llm. Same provider-swap rule via LLM_PROVIDER.
    Routers pass raw image bytes + mime type; this handles encoding."""
    if settings.LLM_PROVIDER == "anthropic":
        return await _ask_anthropic_vision(image_bytes, mime_type, prompt, system)
    return await _ask_groq_vision(image_bytes, mime_type, prompt, system)
