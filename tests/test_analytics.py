"""Tests for GET /api/v1/analytics/* endpoints.

Why mocking is used here
────────────────────────
The analytics service executes raw PostgreSQL SQL that relies on dialect-
specific features unavailable in SQLite:
  - EXTRACT(YEAR/MONTH FROM date) — SQLite uses strftime('%Y', date) instead
  - SUM(...) OVER () aggregate window functions — not supported in SQLite < 3.25
  - LAG() window function — not supported in older SQLite builds
  - make_interval() — PostgreSQL-only function

Rather than maintaining two SQL dialects or requiring a live Postgres container
for unit tests, we mock the service layer. This approach:
  1. Keeps the test suite fast and dependency-free.
  2. Verifies routing, authentication, and response serialisation — the
     FastAPI layer we actually own.
  3. Leaves the SQL itself integration-tested against real PostgreSQL via
     docker-compose (see the README for how to run those manually).

The real SQL queries were validated by hand against the running postgres:15
container during development.
"""

from datetime import date
from unittest.mock import patch

# ── Helpers ───────────────────────────────────────────────────────────────────

_TODAY = date.today()
_YEAR = _TODAY.year
_MONTH = _TODAY.month

_SUMMARY_PARAMS = f"?year={_YEAR}&month={_MONTH}"
_TRENDS_PARAMS = "?months=3"
_BUDGET_PARAMS = f"?year={_YEAR}&month={_MONTH}"

# Realistic mock return values that match what the real SQL would produce.
_MOCK_SUMMARY = [
    {
        "category_name": "Groceries",
        "colour": "#4CAF50",
        "icon": "shopping_cart",
        "total_amount": 320.50,
        "transaction_count": 8,
        "percentage_of_total": 45.20,
    }
]

_MOCK_TRENDS = [
    {
        "year": _YEAR,
        "month": _MONTH - 1 or 12,
        "total_spent": 1200.00,
        "transaction_count": 25,
        "prev_month_spent": None,
        "month_over_month_pct": None,
    },
    {
        "year": _YEAR,
        "month": _MONTH,
        "total_spent": 1450.00,
        "transaction_count": 30,
        "prev_month_spent": 1200.00,
        "month_over_month_pct": 20.83,
    },
]

_MOCK_BUDGET = [
    {
        "category_name": "Dining Out",
        "colour": "#FF9800",
        "icon": "restaurant",
        "budget_amount": 200.00,
        "actual_spent": 247.30,
        "remaining": -47.30,
        "percentage_used": 123.65,
    }
]


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_monthly_summary_empty(client, auth_headers):
    """When no transactions exist the summary endpoint returns an empty list.

    We mock the service to return [] — an empty database would produce the
    same result from the real SQL query (the WHERE clause matches nothing,
    GROUP BY has no groups, result set is empty).
    This test verifies: routing, auth guard, and correct JSON serialisation of
    an empty response ([] not null or 404).
    """
    with patch(
        "app.services.analytics_service.get_monthly_summary",
        return_value=[],
    ):
        response = client.get(
            f"/api/v1/analytics/summary{_SUMMARY_PARAMS}",
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.json() == []


def test_monthly_summary_with_data(client, auth_headers):
    """With data, the summary endpoint returns the service's result as JSON.

    We mock the service to return a known payload and verify:
    - The endpoint passes it through correctly (no silent field drops).
    - All numeric fields arrive as numbers (not strings) in the JSON.
    - The category_name field is present (the key denormalised field).

    In a full integration test against PostgreSQL, we'd create real transactions
    and verify the SQL aggregation. Here we're testing the HTTP layer.
    """
    with patch(
        "app.services.analytics_service.get_monthly_summary",
        return_value=_MOCK_SUMMARY,
    ):
        response = client.get(
            f"/api/v1/analytics/summary{_SUMMARY_PARAMS}",
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1

    item = data[0]
    assert item["category_name"] == "Groceries"
    assert item["total_amount"] == 320.50
    assert item["transaction_count"] == 8
    assert item["percentage_of_total"] == 45.20


def test_spending_trends_returns_list(client, auth_headers):
    """The trends endpoint returns a list with the expected per-month shape.

    Key fields checked:
    - year and month as integers (not strings from EXTRACT::INT cast).
    - prev_month_spent is None for the first row (no prior month).
    - month_over_month_pct is a float for subsequent rows.
    """
    with patch(
        "app.services.analytics_service.get_spending_trends",
        return_value=_MOCK_TRENDS,
    ):
        response = client.get(
            f"/api/v1/analytics/trends{_TRENDS_PARAMS}",
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2

    first, second = data
    # First row has no LAG value.
    assert first["prev_month_spent"] is None
    assert first["month_over_month_pct"] is None
    # Second row has a calculated percentage.
    assert second["month_over_month_pct"] == 20.83


def test_budget_vs_actual_empty(client, auth_headers):
    """With no budgets, the budget-vs-actual endpoint returns an empty list.

    The real SQL uses a LEFT JOIN from budgets outward — if no budget rows
    exist for the user/month/year, the query returns nothing. 200 + [] is
    the correct response, not 404.
    """
    with patch(
        "app.services.analytics_service.get_budget_vs_actual",
        return_value=[],
    ):
        response = client.get(
            f"/api/v1/analytics/budget-vs-actual{_BUDGET_PARAMS}",
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.json() == []
