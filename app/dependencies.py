from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import decode_access_token
from app.core.database import get_db
from app.models import User

FREE_EXAMINATION_LIMIT = 3


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Resolves the caller's account from an `Authorization: Bearer <token>`
    header. Raises 401 if missing/invalid — use this on any route that
    needs to know *who* is calling but doesn't need to gate on quota."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    token = authorization.removeprefix("Bearer ").strip()
    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer exists")

    return user


def require_quota(user: User = Depends(get_current_user)) -> User:
    """Use this in place of get_current_user on /api/detect and
    /api/detect-image. Rejects the request BEFORE any LLM call is made if
    a free-plan account has used its 3 examinations — so a maxed-out
    account can't burn your Groq/Anthropic quota by hammering the API
    directly, even bypassing the frontend entirely."""
    if user.plan == "free" and user.examinations_used >= FREE_EXAMINATION_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Free plan limit reached ({FREE_EXAMINATION_LIMIT} examinations). "
                "Upgrade to Pro for unlimited examinations."
            ),
        )
    return user


def consume_examination(db: Session, user: User) -> None:
    """Call this AFTER a successful verdict is produced — not before —
    so a failed LLM call or a malformed request doesn't burn one of the
    user's free examinations for nothing."""
    if user.plan == "free":
        user.examinations_used += 1
        db.add(user)
        db.commit()
