from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ── Base ──────────────────────────────────────────────────────────────────────
class UserBase(BaseModel):
    """Fields shared by every user-facing schema.

    EmailStr (from pydantic[email]) validates that the value is a syntactically
    valid email address. It normalises the domain to lowercase automatically,
    so "User@Gmail.COM" becomes "User@gmail.com" in the stored value.
    """

    email: EmailStr


# ── Write schemas (inbound) ───────────────────────────────────────────────────
class UserCreate(UserBase):
    """Payload accepted when registering a new user.

    The plain-text password is received here and immediately hashed by the
    service layer before anything is persisted. It is intentionally absent
    from every response schema so it can never leak through the API.

    min_length=8 is a basic policy guard enforced before the data reaches the
    route handler — no need to check again inside the service.
    """

    password: str = Field(..., min_length=8)


# ── Read schemas (outbound) ───────────────────────────────────────────────────
class UserResponse(UserBase):
    """Shape of the user object returned by the API.

    Never includes hashed_password — that field simply has no place in this
    schema, so it cannot accidentally appear in a response.

    from_attributes=True (formerly orm_mode=True in Pydantic v1) lets Pydantic
    read values from SQLAlchemy ORM instances via attribute access instead of
    dict lookup. Without this, `UserResponse.model_validate(user_orm_object)`
    would raise a validation error.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime


# ── JWT token schemas ─────────────────────────────────────────────────────────
class Token(BaseModel):
    """Response body returned from the /auth/login endpoint.

    access_token: the signed JWT string the client must include in every
                  subsequent request as: Authorization: Bearer <token>
    token_type:   always "bearer" per OAuth2 spec; included so clients don't
                  need to hard-code it.
    """

    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Claims extracted from a decoded JWT.

    We only embed email in the token payload ('sub' claim) so the recipient
    can look up the full user record without coupling the token size to the
    user object. Optional because decoding can fail before the claim is read.
    """

    email: Optional[str] = None
