import asyncio
import json
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import consume_examination, require_quota
from app.models import User
from app.services import image_forensics
from app.services.llm_client import ask_llm_vision

router = APIRouter()

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}

SYSTEM_PROMPT = (
    "You are a careful image-provenance analyst. You are shown an image plus a "
    "set of deterministic forensic findings already extracted from its file "
    "metadata (EXIF, embedded generation parameters, AI-tool fingerprints). "
    "Actively look at the image for visual tells of AI generation: hands, "
    "teeth, ears, or jewelry rendered wrong; text/lettering that's garbled; "
    "backgrounds that warp or repeat; lighting/shadows inconsistent with a "
    "single light source; skin, hair, or fabric texture that looks airbrushed "
    "or too uniform; reflections that don't match the scene. Weigh this "
    "against the forensic findings you're given - a strong metadata "
    "fingerprint (a named AI tool, embedded generation parameters) should "
    "dominate your verdict even if the image looks visually convincing, and "
    "you should say so if that's what happened. Absence of metadata is NOT "
    "evidence of human origin - many real photos lose EXIF through messaging "
    "apps and social media export, so do not treat missing metadata as proof "
    "either way. Be honest about uncertainty - do not force a confident "
    "verdict when the visual and forensic signal is genuinely weak or mixed. "
    "Respond with ONLY a JSON object, no other text, no markdown fences, in "
    'exactly this shape: {"verdict": "ai" or "human", "confidence": integer '
    "0-100, \"reasoning\": a single plain sentence, under 30 words, citing the "
    'specific signal (visual or forensic) that drove the verdict}.'
)


class ForensicSignalOut(BaseModel):
    id: str
    label: str
    strength: str
    points_to: str
    detail: str


class DetectImageResponse(BaseModel):
    verdict: str
    confidence: int
    reasoning: str
    forensic_signals: list[ForensicSignalOut]
    degraded_mode: bool


def _extract_json(raw: str) -> dict:
    """Same approach as detect.py's helper - LLMs sometimes wrap JSON in
    markdown fences or add stray text despite instructions."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model response")
    return json.loads(match.group(0))


def _fuse_verdict(report: image_forensics.ForensicReport, llm_verdict: dict | None) -> tuple[str, int, str]:
    """Returns (verdict, confidence, reasoning). If the LLM call failed,
    falls back to a forensics-only verdict rather than erroring the whole
    request - a lower-confidence answer beats a 502 for something users
    will hammer with random screenshots."""
    score = report.heuristic_score  # -1 (human-leaning) .. +1 (ai-leaning)

    if llm_verdict is None:
        if score > 0.5:
            return "ai", 65, (
                "Vision model was unavailable; verdict is based on a strong "
                "AI-generator fingerprint found in the image's embedded metadata."
            )
        return "human", 30, (
            "Vision model was unavailable and file metadata alone was not "
            "conclusive - this is a low-confidence fallback verdict."
        )

    llm_says_ai = llm_verdict.get("verdict") == "ai"
    reasoning = str(llm_verdict.get("reasoning", "")).strip() or "No specific reasoning returned."
    try:
        confidence = int(llm_verdict.get("confidence", 50))
    except (TypeError, ValueError):
        confidence = 50
    confidence = max(0, min(100, confidence))

    # Strong forensic fingerprint disagrees with the LLM's visual read ->
    # trust the fingerprint, but say plainly that we're overriding.
    if score > 0.7 and not llm_says_ai:
        return "ai", 85, (
            "Embedded file metadata contains a strong AI-generator fingerprint, "
            "which overrides a visual-only read of human origin."
        )

    # Forensics agrees with the LLM -> small confidence boost, capped at 99.
    if (llm_says_ai and score > 0.3) or (not llm_says_ai and score < -0.15):
        confidence = min(99, confidence + 10)

    return ("ai" if llm_says_ai else "human"), confidence, reasoning


@router.post("/api/detect-image", response_model=DetectImageResponse)
async def detect_image(
    file: UploadFile = File(...),
    current_user: User = Depends(require_quota),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{file.content_type}'. "
                   f"Accepted: {', '.join(sorted(ALLOWED_MIME_TYPES))}.",
        )

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file upload.")
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(image_bytes) // 1024} KB). "
                   f"Max is {MAX_UPLOAD_BYTES // 1024 // 1024} MB.",
        )

    # Pillow decode + EXIF parse is CPU-bound; keep it off the event loop.
    report = await asyncio.to_thread(image_forensics.analyze_image, image_bytes)
    forensic_context = report.to_dict()

    prompt = (
        "Deterministic forensic findings for this image (from file metadata, "
        f"not visual inspection):\n\n{json.dumps(forensic_context, indent=2)}\n\n"
        "Now examine the attached image itself and return the fused JSON verdict."
    )

    llm_verdict = None
    try:
        raw = await ask_llm_vision(image_bytes, file.content_type, prompt, system=SYSTEM_PROMPT)
        parsed = _extract_json(raw)
        if str(parsed.get("verdict", "")).lower().strip() in ("ai", "human"):
            parsed["verdict"] = str(parsed["verdict"]).lower().strip()
            llm_verdict = parsed
        # else: leave llm_verdict as None -> falls back to forensics-only path
    except Exception:
        llm_verdict = None

    verdict, confidence, reasoning = _fuse_verdict(report, llm_verdict)

    # Only counts against the free quota once we actually have a verdict to
    # show for it (forensics-only fallback still counts - it's still a
    # completed examination, just degraded_mode=True).
    consume_examination(db, current_user)

    return DetectImageResponse(
        verdict=verdict,
        confidence=confidence,
        reasoning=reasoning,
        forensic_signals=[ForensicSignalOut(**s.__dict__) for s in report.signals],
        degraded_mode=llm_verdict is None,
    )
