from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── Base ──────────────────────────────────────────────────────────────────────
class BudgetBase(BaseModel):
    """Fields required to define a monthly budget for a category."""

    # The category this budget applies to. user_id is not accepted here —
    # it is read from the authenticated JWT in the route handler so users
    # cannot set budgets on other users' categories.
    category_id: int

    # Planned spend ceiling for the month. Must be positive — a zero or
    # negative budget is nonsensical and likely a client-side form error.
    amount: Decimal = Field(..., gt=0, decimal_places=2)

    # ge=1, le=12 enforces the calendar month range at the Pydantic layer,
    # matching the comment in budget.py that says "application layer must validate".
    month: int = Field(..., ge=1, le=12)

    # Four-digit year. ge=2000 prevents obviously bogus historical entries;
    # le=2100 is a soft upper bound — adjust if your app outlives us all.
    year: int = Field(..., ge=2000, le=2100)

    @model_validator(mode="after")
    def month_year_combination_is_plausible(self) -> "BudgetBase":
        """Cross-field guard: reject month/year combos that are clearly wrong.

        Individual field validators run before this, so by the time we get here
        month is guaranteed to be 1-12 and year 2000-2100. This hook is a
        placeholder for any future cross-field business rules (e.g. "no budgets
        more than 12 months in the past").
        """
        return self


# ── Write schemas (inbound) ───────────────────────────────────────────────────
class BudgetCreate(BudgetBase):
    """Payload for creating a new monthly budget.

    The uniqueness of (user_id, category_id, month, year) is enforced by the
    DB constraint uq_budget_user_category_month_year. The service layer should
    catch IntegrityError and surface a 409 Conflict rather than letting a 500
    propagate to the client.
    """


# ── Read schemas (outbound) ───────────────────────────────────────────────────
class BudgetResponse(BudgetBase):
    """Budget data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
