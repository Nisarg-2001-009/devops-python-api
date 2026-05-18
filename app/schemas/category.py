import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Base ──────────────────────────────────────────────────────────────────────
class CategoryBase(BaseModel):
    """Fields shared by category write and read schemas."""

    name: str = Field(..., min_length=1, max_length=100)

    # Optional hex colour code for UI badges, e.g. "#FF5733".
    # Validated below to ensure the format is exactly #RRGGBB — the DB column
    # is String(7) so a bad value would either truncate or raise a DB error
    # without this check.
    colour: Optional[str] = Field(default=None, max_length=7)

    # Icon identifier (e.g. Material Icon name or emoji shortcode).
    icon: Optional[str] = Field(default=None, max_length=50)

    # False = expense category (most common); True = income category.
    # Defaults to False so callers creating expense categories can omit the field.
    is_income: bool = False

    @field_validator("colour")
    @classmethod
    def validate_hex_colour(cls, v: Optional[str]) -> Optional[str]:
        """Reject any colour string that isn't a valid #RRGGBB hex code."""
        if v is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            raise ValueError("colour must be a valid hex code, e.g. '#FF5733'")
        return v


# ── Write schemas (inbound) ───────────────────────────────────────────────────
class CategoryCreate(CategoryBase):
    """Payload for creating a new category.

    No additional fields beyond the base — user_id is injected by the route
    from the authenticated JWT, not supplied by the client. This prevents one
    user from creating categories on behalf of another.
    """


# ── Read schemas (outbound) ───────────────────────────────────────────────────
class CategoryResponse(CategoryBase):
    """Category data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
