import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import consume_examination, require_quota
from app.models import User
from app.services.llm_client import ask_llm

router = APIRouter()

MIN_CHARS = 40
MAX_CHARS = 6000

SYSTEM_PROMPT = (
    "You are a careful text-forensics analyst. You examine writing samples for "
    "statistical and stylistic signals of large-language-model generation: "
    "uniform sentence length, hedging phrases, generic transitions, absence of "
    "specific lived detail, overly balanced structure, and repetitive rhetorical "
    "patterns. You also weigh signals of human writing: irregular rhythm, "
    "specific concrete detail, idiosyncratic word choice, typos, informal "
    "asides. You are honest about uncertainty - real text is often ambiguous, "
    "and you should not force a confident verdict when the signal is weak. "
    "Respond with ONLY a JSON object, no other text, no markdown fences, in "
    'exactly this shape: {"verdict": "ai" or "human", "confidence": integer '
    "0-100, \"reasoning\": a single plain sentence, under 30 words, citing the "
    'specific signals that drove the verdict}.'
)


class DetectRequest(BaseModel):
    text: str = Field(..., min_length=1)


class DetectResponse(BaseModel):
    verdict: str
    confidence: int
    reasoning: str


def _extract_json(raw: str) -> dict:
    """LLMs sometimes wrap JSON in markdown fences or add stray text despite
    instructions. Strip fences, then grab the first {...} block."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model response")
    return json.loads(match.group(0))


@router.post("/api/detect", response_model=DetectResponse)
async def detect(
    payload: DetectRequest,
    current_user: User = Depends(require_quota),
    db: Session = Depends(get_db),
):
    text = payload.text.strip()

    if len(text) < MIN_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Paste at least {MIN_CHARS} characters - too little text to judge reliably.",
        )
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    prompt = f'Analyze this text and return the verdict JSON:\n\n"""\n{text}\n"""'

    try:
        raw = await ask_llm(prompt, system=SYSTEM_PROMPT)
        parsed = _extract_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}")

    verdict = str(parsed.get("verdict", "")).lower().strip()
    if verdict not in ("ai", "human"):
        raise HTTPException(status_code=502, detail="Model returned an unrecognized verdict")

    try:
        confidence = int(parsed.get("confidence", 50))
    except (TypeError, ValueError):
        confidence = 50
    confidence = max(0, min(100, confidence))

    reasoning = str(parsed.get("reasoning", "")).strip() or "No specific reasoning returned."

    # Only counts against the free quota once we actually have a verdict to
    # show for it - a failed LLM call above never reaches this line.
    consume_examination(db, current_user)

    return DetectResponse(verdict=verdict, confidence=confidence, reasoning=reasoning)
