from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.security import get_current_user
from app.database import get_db
from app.models.user import User
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])

# Default to the current month/year so callers can hit the endpoint with no
# params and immediately see useful data.
_today = date.today()
_current_year = _today.year
_current_month = _today.month


@router.get(
    "/summary",
    summary="Monthly spending breakdown by category",
)
def monthly_summary(
    year: int = Query(default=_current_year, ge=2000, le=2100),
    month: int = Query(default=_current_month, ge=1, le=12),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return per-category spending totals and percentage of total spend.

    Uses an aggregate window function (SUM OVER) to calculate each category's
    share of total spending in a single SQL pass — no application-side division
    loop required.

    Example response item:
      {
        "category_name": "Groceries",
        "colour": "#4CAF50",
        "icon": "shopping_cart",
        "total_amount": 320.50,
        "transaction_count": 12,
        "percentage_of_total": 18.45
      }
    """
    return analytics_service.get_monthly_summary(db, current_user.id, year, month)


@router.get(
    "/trends",
    summary="Month-over-month spending trends",
)
def spending_trends(
    months: int = Query(
        default=6,
        ge=1,
        le=24,
        description="Number of past months to include",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return monthly spending totals with LAG-based month-over-month change %.

    Uses a CTE + LAG() window function to compare each month against the
    previous month without a self-join.

    Example response item:
      {
        "year": 2025,
        "month": 3,
        "total_spent": 1840.00,
        "transaction_count": 47,
        "prev_month_spent": 1620.00,
        "month_over_month_pct": 13.58
      }

    month_over_month_pct is null for the earliest month in the window
    (no previous month to compare to).
    """
    return analytics_service.get_spending_trends(db, current_user.id, months)


@router.get(
    "/budget-vs-actual",
    summary="Budget targets vs actual spending per category",
)
def budget_vs_actual(
    year: int = Query(default=_current_year, ge=2000, le=2100),
    month: int = Query(default=_current_month, ge=1, le=12),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Compare each budget against actual spend for the given month.

    Uses a LEFT JOIN with a derived table subquery to show budget rows even
    when no transactions exist for a category (actual_spent = 0).

    Example response item:
      {
        "category_name": "Dining Out",
        "colour": "#FF9800",
        "icon": "restaurant",
        "budget_amount": 200.00,
        "actual_spent": 247.30,
        "remaining": -47.30,
        "percentage_used": 123.65
      }

    remaining is negative when the budget is exceeded. Results are sorted
    by percentage_used DESC so the most over-budget categories appear first.
    """
    return analytics_service.get_budget_vs_actual(db, current_user.id, year, month)
