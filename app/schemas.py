from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="At least 8 characters.")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: EmailStr
    plan: str
    examinations_used: int
    # None means unlimited (Pro). A number means "this many free
    # examinations left" for a Free account.
    examinations_remaining: Optional[int]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
