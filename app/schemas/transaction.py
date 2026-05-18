from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Base ──────────────────────────────────────────────────────────────────────
class TransactionBase(BaseModel):
    """Fields required to record a money movement."""

    # Which account this transaction debits or credits.
    account_id: int

    # Category is optional — a transaction can be uncategorised and tagged later.
    category_id: Optional[int] = None

    # Decimal preserves the exact two-decimal-place precision of Numeric(12, 2).
    # Using float here would introduce rounding errors that accumulate over
    # thousands of rows (e.g. 0.1 + 0.2 != 0.3 in IEEE 754).
    # Sign convention: positive = money in, negative = money out.
    amount: Decimal = Field(..., decimal_places=2)

    # Optional memo / payee name. 500 matches the DB column width.
    description: Optional[str] = Field(default=None, max_length=500)

    # The date the transaction occurred as reported by the bank.
    # Stored as Date (no time component) because bank exports rarely include
    # an accurate timestamp and it is not needed for monthly reporting.
    transaction_date: date

    @field_validator("amount")
    @classmethod
    def amount_must_not_be_zero(cls, v: Decimal) -> Decimal:
        """A zero-value transaction is meaningless and likely a client bug."""
        if v == 0:
            raise ValueError("amount must not be zero")
        return v


# ── Write schemas (inbound) ───────────────────────────────────────────────────
class TransactionCreate(TransactionBase):
    """Payload for recording a new transaction.

    account_id is accepted from the client here (unlike user_id on other
    schemas) because a user can have multiple accounts and must specify which
    one is affected. The service layer verifies that the account belongs to the
    authenticated user before inserting — never trust the FK alone.
    """


# ── Read schemas (outbound) ───────────────────────────────────────────────────
class TransactionResponse(TransactionBase):
    """Transaction data returned by the API.

    category_name is a denormalised convenience field: the client receives the
    human-readable category name in the same response instead of making a
    second request to /categories/{id}. It is Optional because category_id may
    be NULL (uncategorised transaction).

    To populate category_name from the ORM relationship, the service layer sets
    it explicitly:
        response.category_name = transaction.category.name if transaction.category else None

    Alternatively, a @computed_field on the response schema could read
    self.category.name, but that requires passing the full ORM object through
    Pydantic, which leaks ORM internals into the schema layer.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    category_name: Optional[str] = None
