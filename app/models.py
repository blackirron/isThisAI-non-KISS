import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime

from app.core.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_new_id)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    # "free" | "pro" — upgrade/downgrade endpoints are placeholders until
    # real billing (Stripe) is wired in; see app/routers/auth.py.
    plan = Column(String, nullable=False, default="free")

    # Only meaningful for free-plan accounts; ignored once plan == "pro".
    examinations_used = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
