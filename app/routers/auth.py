from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import create_access_token, hash_password, verify_password
from app.core.database import get_db
from app.dependencies import FREE_EXAMINATION_LIMIT, get_current_user
from app.models import User
from app.schemas import LoginRequest, SignupRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    remaining = None if user.plan == "pro" else max(0, FREE_EXAMINATION_LIMIT - user.examinations_used)
    return UserOut(
        id=user.id,
        email=user.email,
        plan=user.plan,
        examinations_used=user.examinations_used,
        examinations_remaining=remaining,
    )


@router.post("/signup", response_model=TokenResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(email=email, hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=_user_out(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return _user_out(current_user)


@router.post("/downgrade", response_model=UserOut)
def downgrade(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Self-service switch back to Free. Kept mainly for testing the paywall
    repeatedly without creating new accounts — real Pro purchases are a
    one-time payment (see app/routers/payments.py), so there's no refund
    logic tied to this; it just flips the flag back."""
    current_user.plan = "free"
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return _user_out(current_user)
