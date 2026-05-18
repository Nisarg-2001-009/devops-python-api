from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Exhaustive list of supported account types. Using Literal here means Pydantic
# rejects any other string before the data reaches the route handler, surfacing a
# clear 422 Unprocessable Entity with the exact allowed values — no custom
# validator needed.
AccountType = Literal["checking", "savings", "credit", "cash"]


# ── Base ──────────────────────────────────────────────────────────────────────
class AccountBase(BaseModel):
    """Fields common to create and response schemas."""

    name: str = Field(..., min_length=1, max_length=100)

    # Validated against the Literal union above — anything else is a 422.
    account_type: AccountType

    # ISO 4217 three-letter code. max_length=3 matches the DB column width.
    # "USD" as the default means callers can omit the field for dollar accounts.
    currency: str = Field(default="USD", min_length=3, max_length=3)


# ── Write schemas (inbound) ───────────────────────────────────────────────────
class AccountCreate(AccountBase):
    """Payload for creating a new account.

    balance is excluded from creation: new accounts always start at 0.
    The balance is updated by the service layer as transactions are recorded,
    never set directly by the client. This prevents clients from fabricating
    arbitrary starting balances.
    """


# ── Read schemas (outbound) ───────────────────────────────────────────────────
class AccountResponse(AccountBase):
    """Account data returned by the API.

    balance is included here (read-only) so clients can display the current
    balance without a separate query. Decimal preserves the two-decimal-place
    precision stored in Numeric(12, 2) — JSON serialises it as a string by
    default, which avoids float precision loss in JavaScript.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    balance: Decimal
    created_at: datetime
