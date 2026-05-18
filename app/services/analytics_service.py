"""Advanced SQL analytics using raw SQLAlchemy text() queries.

Raw SQL is chosen over the ORM here because:
  - Window functions (LAG, SUM OVER) have no clean ORM equivalent.
  - Aggregate-over-aggregate expressions like SUM(SUM(x)) OVER () read
    naturally in SQL but require convoluted subquery workarounds in ORM.
  - The analytics queries span multiple tables with complex JOINs and
    GROUP BY clauses where the SQL intent is clearest in plain SQL.

All parameters are passed as bound variables (:name syntax) — never via
string formatting — to prevent SQL injection.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def _rows_to_dicts(rows: Any) -> list[dict]:
    """Convert CursorResult mappings to plain Python dicts.

    Converts Decimal values to float so FastAPI's JSON encoder doesn't need
    special handling. This is intentionally lossy for display purposes —
    financial storage stays as Numeric in the DB.
    """
    result = []
    for row in rows:
        d = dict(row)
        result.append(
            {k: float(v) if isinstance(v, Decimal) else v for k, v in d.items()}
        )
    return result


# ── 1. Monthly category summary ───────────────────────────────────────────────

def get_monthly_summary(
    db: Session, user_id: int, year: int, month: int
) -> list[dict]:
    """Return per-category spending breakdown for a given month.

    SQL features used:
      - LEFT JOIN to categories: uncategorised transactions appear as
        'Uncategorised' via COALESCE rather than being silently dropped.
      - Aggregate window function SUM(SUM(...)) OVER (): calculates the grand
        total across all groups in a single pass, avoiding a self-join or
        correlated subquery.
        Outer SUM is the window; inner SUM is the per-group aggregate.
      - NULLIF(..., 0): prevents division-by-zero when total spend is 0.
      - EXTRACT(YEAR/MONTH FROM date): Postgres date part extraction; faster
        than BETWEEN on a full date range for this use case.
      - ABS(t.amount): amounts are signed (negative = expense); we display
        absolute values so the UI shows "spent $50" not "spent -$50".
      - ORDER BY total_amount DESC: largest categories first for dashboard display.
    """
    sql = text("""
        SELECT
            COALESCE(c.name, 'Uncategorised')   AS category_name,
            c.colour,
            c.icon,
            SUM(ABS(t.amount))                  AS total_amount,
            COUNT(t.id)                         AS transaction_count,
            ROUND(
                SUM(ABS(t.amount)) * 100.0
                / NULLIF(SUM(SUM(ABS(t.amount))) OVER (), 0),
                2
            )                                   AS percentage_of_total
        FROM transactions t
        JOIN     accounts   a ON a.id = t.account_id
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE a.user_id = :user_id
          AND t.amount  < 0
          AND EXTRACT(YEAR  FROM t.transaction_date) = :year
          AND EXTRACT(MONTH FROM t.transaction_date) = :month
        GROUP BY c.id, c.name, c.colour, c.icon
        ORDER BY total_amount DESC
    """)

    result = db.execute(sql, {"user_id": user_id, "year": year, "month": month})
    return _rows_to_dicts(result.mappings().all())


# ── 2. Spending trends with month-over-month change ───────────────────────────

def get_spending_trends(
    db: Session, user_id: int, months: int = 6
) -> list[dict]:
    """Return monthly spending totals with month-over-month change % for the last N months.

    SQL features used:
      - CTE (WITH monthly_totals AS ...): materialises the per-month aggregates
        once so the window functions in the outer query reference the CTE rows
        rather than re-scanning the transactions table.
      - LAG(total_spent) OVER (ORDER BY year, month): accesses the previous
        month's value within the ordered result set without a self-join.
        NULL for the first row (no previous month to compare to).
      - Percentage change formula: (current - previous) / previous * 100.
        Positive = spending increased; negative = spending decreased.
      - NULLIF(LAG(...), 0): avoids division-by-zero if a previous month had 0 spend.
      - ::INT cast on EXTRACT: Postgres returns EXTRACT as double precision;
        casting makes downstream handling simpler.

    start_date is computed in Python (not SQL) to avoid parameterising an
    INTERVAL expression, which psycopg2 does not support directly.
    """
    # Compute the first day of the month N months ago.
    today = date.today()
    start_month = today.month - months
    start_year = today.year
    # Roll back the year for each 12-month boundary crossed.
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    start_date = date(start_year, start_month, 1)

    sql = text("""
        WITH monthly_totals AS (
            SELECT
                EXTRACT(YEAR  FROM t.transaction_date)::INT  AS year,
                EXTRACT(MONTH FROM t.transaction_date)::INT  AS month,
                SUM(ABS(t.amount))                           AS total_spent,
                COUNT(t.id)                                  AS transaction_count
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.user_id  = :user_id
              AND t.amount   < 0
              AND t.transaction_date >= :start_date
            GROUP BY year, month
        )
        SELECT
            year,
            month,
            total_spent,
            transaction_count,
            LAG(total_spent) OVER (ORDER BY year, month)    AS prev_month_spent,
            ROUND(
                (total_spent - LAG(total_spent) OVER (ORDER BY year, month))
                * 100.0
                / NULLIF(LAG(total_spent) OVER (ORDER BY year, month), 0),
                2
            )                                               AS month_over_month_pct
        FROM monthly_totals
        ORDER BY year, month
    """)

    result = db.execute(sql, {"user_id": user_id, "start_date": start_date})
    return _rows_to_dicts(result.mappings().all())


# ── 3. Budget vs actual spend ─────────────────────────────────────────────────

def get_budget_vs_actual(
    db: Session, user_id: int, year: int, month: int
) -> list[dict]:
    """Compare each budget against actual spending for the given month.

    SQL features used:
      - Correlated subquery as a derived table (act): aggregates the actual
        spend per category for the month, then LEFT JOINs to budgets so that
        categories with a budget but no transactions still appear (COALESCE
        fills their actual_spent with 0).
      - COALESCE(act.total_spent, 0): categories with no transactions this
        month produce NULL from the LEFT JOIN; COALESCE makes them 0 so
        arithmetic on remaining and percentage_used doesn't produce NULL.
      - remaining = budget − actual: negative values indicate overspending,
        which the UI can highlight in red.
      - NULLIF(b.amount, 0): guards against a zero-budget row (shouldn't exist
        given our schema validation, but defensive SQL is good SQL).
      - ORDER BY percentage_used DESC NULLS LAST: most-used budgets first;
        NULLS LAST pushes any NULL percentages (e.g. $0 budget rows) to the end.
    """
    sql = text("""
        SELECT
            c.name                                    AS category_name,
            c.colour,
            c.icon,
            b.amount                                  AS budget_amount,
            COALESCE(act.total_spent, 0)              AS actual_spent,
            b.amount - COALESCE(act.total_spent, 0)   AS remaining,
            ROUND(
                COALESCE(act.total_spent, 0) * 100.0
                / NULLIF(b.amount, 0),
                2
            )                                         AS percentage_used
        FROM budgets b
        JOIN categories c ON c.id = b.category_id
        LEFT JOIN (
            -- Derived table: actual spend per category for this user/month/year.
            -- Using a subquery here rather than a second GROUP BY on the outer
            -- query keeps the JOIN cardinality predictable (one row per category).
            SELECT
                t.category_id,
                SUM(ABS(t.amount)) AS total_spent
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.user_id = :user_id
              AND t.amount  < 0
              AND EXTRACT(YEAR  FROM t.transaction_date) = :year
              AND EXTRACT(MONTH FROM t.transaction_date) = :month
            GROUP BY t.category_id
        ) act ON act.category_id = b.category_id
        WHERE b.user_id = :user_id
          AND b.month   = :month
          AND b.year    = :year
        ORDER BY percentage_used DESC NULLS LAST
    """)

    result = db.execute(
        sql, {"user_id": user_id, "year": year, "month": month}
    )
    return _rows_to_dicts(result.mappings().all())
