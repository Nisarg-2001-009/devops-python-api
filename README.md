# Personal Finance Tracker API

A production-grade REST API for personal finance management built with FastAPI, PostgreSQL, and SQLAlchemy. Demonstrates JWT authentication, atomic database operations, advanced SQL analytics (window functions, CTEs, derived-table subqueries), and a fully containerised Docker workflow.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Framework | FastAPI 0.136 | Async-capable, auto-generates OpenAPI docs, Pydantic-native |
| Database | PostgreSQL 15 (Alpine) | ACID transactions, window functions, Numeric type for money |
| ORM | SQLAlchemy 2.x | Declarative models, connection pooling, dialect abstraction |
| Migrations | Alembic | Schema versioning with autogenerate from ORM metadata |
| Validation | Pydantic v2 + pydantic-settings | Runtime type enforcement, `.env` config loading |
| Auth | JWT via python-jose + bcrypt | Stateless auth; bcrypt for password hashing |
| Containers | Docker + Docker Compose | Reproducible environment for API, Postgres, pgAdmin |
| Testing | pytest + httpx + SQLite | Fast unit tests without a running Postgres instance |

---

## Architecture

```
 HTTP Request
      │
      ▼
┌─────────────────────────────────────────────────┐
│              FastAPI  (app/main.py)              │
│         CORS Middleware · OpenAPI /docs          │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│            Routers  (app/routers/)               │
│   /auth   /accounts   /transactions             │
│   /analytics                                    │
│                                                 │
│   • JWT auth via Depends(get_current_user)      │
│   • Pydantic request/response schemas           │
└────────────────────┬────────────────────────────┘
                     │  function calls
                     ▼
┌─────────────────────────────────────────────────┐
│            Services  (app/services/)             │
│                                                 │
│   user_service      account_service             │
│   transaction_service                           │
│   analytics_service  ← raw SQL (text())         │
│                                                 │
│   • Business logic & ownership checks           │
│   • SELECT FOR UPDATE for atomic balance ops    │
└─────────────┬───────────────────┬───────────────┘
              │ SQLAlchemy ORM    │ sqlalchemy.text()
              ▼                   ▼
┌─────────────────────────────────────────────────┐
│              Data Layer                          │
│                                                 │
│  ORM Models (app/models/)                       │
│  users · accounts · categories                  │
│  transactions · budgets                         │
│                                                 │
│  Alembic migrations (alembic/versions/)         │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│           PostgreSQL 15 (Docker)                 │
│                                                 │
│  financedb  ·  port 5432                        │
│  pgAdmin UI ·  port 5050                        │
└─────────────────────────────────────────────────┘
```

---

## API Endpoints

All protected endpoints require `Authorization: Bearer <token>` obtained from `/api/v1/auth/login`.

### Auth

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/auth/register` | No | Create a new user account |
| `POST` | `/api/v1/auth/login` | No | Exchange credentials for a JWT access token |

### Accounts

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/v1/accounts` | Yes | List all accounts for the current user |
| `POST` | `/api/v1/accounts` | Yes | Create a new account (balance starts at 0) |
| `GET` | `/api/v1/accounts/{id}` | Yes | Get a single account by ID |

### Transactions

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/transactions` | Yes | Record a transaction; atomically updates account balance |
| `GET` | `/api/v1/transactions` | Yes | List transactions (filters: `account_id`, `category_id`, `start_date`, `end_date`, `skip`, `limit`) |
| `GET` | `/api/v1/transactions/{id}` | Yes | Get a single transaction |
| `DELETE` | `/api/v1/transactions/{id}` | Yes | Delete transaction and reverse balance effect |

### Analytics

| Method | Path | Auth | Query Params | Description |
|--------|------|------|--------------|-------------|
| `GET` | `/api/v1/analytics/summary` | Yes | `year`, `month` | Per-category spend with % of total |
| `GET` | `/api/v1/analytics/trends` | Yes | `months` (default 6) | Month-over-month change using LAG() |
| `GET` | `/api/v1/analytics/budget-vs-actual` | Yes | `year`, `month` | Budget adherence per category |

### Meta

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe — returns status, version, app name |
| `GET` | `/` | Redirects to `/docs` |

---

## Advanced SQL Queries

### 1. Monthly Category Summary — Aggregate Window Function

`GET /api/v1/analytics/summary` uses an **aggregate window function** to calculate each category's percentage of total spend in a single SQL pass, without a self-join or application-side loop:

```sql
SELECT
    COALESCE(c.name, 'Uncategorised') AS category_name,
    SUM(ABS(t.amount))                AS total_amount,
    COUNT(t.id)                       AS transaction_count,
    ROUND(
        SUM(ABS(t.amount)) * 100.0
        / NULLIF(SUM(SUM(ABS(t.amount))) OVER (), 0),
        2
    )                                 AS percentage_of_total
FROM transactions t
JOIN accounts a ON a.id = t.account_id
LEFT JOIN categories c ON c.id = t.category_id
WHERE a.user_id = :user_id
  AND t.amount  < 0
  AND EXTRACT(YEAR FROM t.transaction_date)  = :year
  AND EXTRACT(MONTH FROM t.transaction_date) = :month
GROUP BY c.id, c.name, c.colour, c.icon
ORDER BY total_amount DESC
```

**How `SUM(SUM(ABS(t.amount))) OVER ()` works:** The inner `SUM` is the per-group aggregate (spending per category). The outer `SUM ... OVER ()` is a window function applied to those aggregate values across all groups — producing the grand total. Dividing the group total by the grand total yields the percentage without a subquery.

---

### 2. Spending Trends — CTE + LAG() Window Function

`GET /api/v1/analytics/trends` uses a **CTE** to materialise monthly totals once, then a **LAG()** window function to access the previous month's value without a self-join:

```sql
WITH monthly_totals AS (
    SELECT
        EXTRACT(YEAR  FROM t.transaction_date)::INT AS year,
        EXTRACT(MONTH FROM t.transaction_date)::INT AS month,
        SUM(ABS(t.amount))                          AS total_spent,
        COUNT(t.id)                                 AS transaction_count
    FROM transactions t
    JOIN accounts a ON a.id = t.account_id
    WHERE a.user_id = :user_id AND t.amount < 0
      AND t.transaction_date >= :start_date
    GROUP BY year, month
)
SELECT
    year, month, total_spent, transaction_count,
    LAG(total_spent) OVER (ORDER BY year, month)    AS prev_month_spent,
    ROUND(
        (total_spent - LAG(total_spent) OVER (ORDER BY year, month))
        * 100.0
        / NULLIF(LAG(total_spent) OVER (ORDER BY year, month), 0),
        2
    )                                               AS month_over_month_pct
FROM monthly_totals
ORDER BY year, month
```

**How LAG() works:** Within the ordered window, `LAG(total_spent)` returns the value from the previous row. For the first row there is no previous row, so NULL is returned. `NULLIF` in the denominator prevents division-by-zero if any prior month had zero spending.

---

### 3. Budget vs Actual — LEFT JOIN with Derived Table Subquery

`GET /api/v1/analytics/budget-vs-actual` uses a **derived table subquery** to aggregate actual spend per category, then **LEFT JOINs** it to the budgets table so budgeted categories with no transactions still appear (with `actual_spent = 0`):

```sql
SELECT
    c.name                                  AS category_name,
    b.amount                                AS budget_amount,
    COALESCE(act.total_spent, 0)            AS actual_spent,
    b.amount - COALESCE(act.total_spent, 0) AS remaining,
    ROUND(COALESCE(act.total_spent, 0) * 100.0 / NULLIF(b.amount, 0), 2)
                                            AS percentage_used
FROM budgets b
JOIN categories c ON c.id = b.category_id
LEFT JOIN (
    SELECT t.category_id, SUM(ABS(t.amount)) AS total_spent
    FROM transactions t
    JOIN accounts a ON a.id = t.account_id
    WHERE a.user_id = :user_id AND t.amount < 0
      AND EXTRACT(YEAR  FROM t.transaction_date) = :year
      AND EXTRACT(MONTH FROM t.transaction_date) = :month
    GROUP BY t.category_id
) act ON act.category_id = b.category_id
WHERE b.user_id = :user_id AND b.month = :month AND b.year = :year
ORDER BY percentage_used DESC NULLS LAST
```

**Why a derived table:** Aggregating actual spend inside a subquery ensures the outer query only sees one row per category (from the budget side). This avoids a Cartesian product between budget and transaction rows that a naive JOIN + GROUP BY would produce. `NULLS LAST` puts categories at 0% used at the bottom of the results.

---

## Setup

### Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)
- Git

### Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd devops-python-api

# 2. Start all services (Postgres, API, pgAdmin)
docker compose up -d --build

# 3. Apply database migrations
#    Run inside the API container where 'db' resolves to the Postgres service
docker compose exec api alembic upgrade head

# 4. Open the interactive API docs
open http://localhost:8000/docs
```

### Services

| Service | URL | Credentials |
|---------|-----|-------------|
| API + Swagger | http://localhost:8000/docs | — |
| pgAdmin | http://localhost:5050 | admin@admin.com / admin |
| PostgreSQL | localhost:5432 | nisarg / password123 / financedb |

### Run Migrations Outside Docker

```bash
# Override the Docker hostname with localhost for local connections
DATABASE_URL=postgresql://nisarg:password123@localhost:5432/financedb \
  alembic upgrade head
```

---

## Running Tests

The test suite uses SQLite and requires no running Docker containers:

```bash
# Install dependencies (if not already installed)
pip install -r requirements.txt

# Run all tests with verbose output
pytest tests/ -v

# Run a specific test file
pytest tests/test_auth.py -v

# Run with coverage report
pytest tests/ --cov=app --cov-report=term-missing
```

**Note on analytics tests:** The analytics tests mock the service layer because the underlying SQL uses PostgreSQL-specific syntax (window functions, `EXTRACT`, aggregate-over-aggregate) not supported by SQLite. The SQL is validated against the real PostgreSQL database via docker-compose during development.

---

## Key Engineering Decisions

### 1. SELECT FOR UPDATE for Atomic Balance Updates

Account balances are updated with `SELECT FOR UPDATE` (pessimistic row-level lock) rather than a read-modify-write cycle. Without the lock, two concurrent transaction requests reading `balance = 1000` would both compute `1000 + delta` and one delta would be silently discarded — the classic lost-update race condition. The lock serialises concurrent writers. `db.flush()` (not `db.commit()`) stages the balance change so the transaction INSERT and the balance UPDATE land in a single atomic commit.

### 2. Raw SQL for Analytics

The analytics service intentionally bypasses the ORM and uses `sqlalchemy.text()` for direct SQL. Window functions (`LAG`, `SUM OVER`), aggregate-over-aggregate expressions, and CTEs have no clean ORM equivalent. Writing them in raw SQL keeps the intent explicit and readable. All parameters use `:name` bound variables — never string formatting — to prevent SQL injection.

### 3. JWT with Email-Only `sub` Claim

The JWT payload contains only `{"sub": email, "exp": ...}`. Embedding the full user object would cause the token to carry stale data (e.g., a deactivated account could continue to authenticate until token expiry). On every protected request, `get_current_user` re-queries the database — one extra round-trip that guarantees freshness and lets account deactivation take effect immediately.

### 4. Pydantic Schema Separation from ORM Models

Request schemas (`UserCreate`, `AccountCreate`) and response schemas (`UserResponse`, `AccountResponse`) are entirely separate from SQLAlchemy models. This boundary means: (a) `hashed_password` can never appear in a response — the field simply doesn't exist in `UserResponse`; (b) `balance` cannot be set by a client at account creation — it's absent from `AccountCreate`; (c) ORM internals never leak into the API contract.

### 5. Alembic for All Schema Changes

Every schema change goes through Alembic rather than raw DDL. `alembic revision --autogenerate` diffs `Base.metadata` against the live database and produces a versioned migration file with `upgrade()` and `downgrade()`. Schema history lives in git alongside code, and any environment can be brought to any revision deterministically.

### 6. Non-Root Docker User

The Dockerfile creates a system user `appuser` and runs the process as that user. If the container is compromised, the attacker has no write access outside `/app` — they cannot install packages, modify system files, or escalate via SUID binaries. The `COPY requirements.txt → pip install → COPY . .` ordering preserves Docker's layer cache: code changes reuse the pip layer; only changes to `requirements.txt` trigger a reinstall.

---

## Bugs Fixed During Development

### 1. passlib Bcrypt Compatibility (bcrypt ≥ 4.x)

**Error encountered:** `ValueError: password cannot be longer than 72 bytes`

**Root cause:** `passlib`'s `CryptContext` performs an internal wrap-detection test during initialisation. It calls `bcrypt.hashpw()` with a sentinel string intentionally longer than 72 bytes to detect a specific passlib behaviour. In `bcrypt` ≥ 4.0, the library enforces the 72-byte bcrypt limit strictly and raises `ValueError` on any input exceeding it — crashing passlib's self-test before a single user password is ever hashed.

**Resolution:** Removed `passlib` entirely and called the `bcrypt` library directly:

```python
# Before — broken with bcrypt >= 4.x
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
hash_password  = lambda p:    pwd_context.hash(p)
verify_password = lambda p, h: pwd_context.verify(p, h)

# After — direct bcrypt, no passlib layer
import bcrypt
hash_password   = lambda p:    bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
verify_password = lambda p, h: bcrypt.checkpw(p.encode("utf-8"), h.encode("utf-8"))
```

Security properties are identical: same algorithm, same automatic per-hash salting, same constant-time comparison. The passlib abstraction layer was the only thing removed.

---

### 2. Docker Layer Cache Not Refreshed After requirements.txt Change

**Symptom:** After adding `pydantic-settings` and `bcrypt` to `requirements.txt` and running `docker compose up --build`, the container launched with stale packages — new dependencies were missing and the app crashed at import time.

**Root cause:** Docker's build cache considers a layer valid if its inputs (file content and preceding layer hash) match a prior build. Under certain WSL2 filesystem conditions, Docker used a stale cache hit for the `COPY requirements.txt .` step — the file metadata comparison succeeded even though the content had changed — so the `pip install` layer was never re-executed.

**Resolution:** Bypass the cache explicitly when changing dependencies:

```bash
docker compose build --no-cache
docker compose up -d
```

The Dockerfile's layer ordering already maximises correct cache usage: `requirements.txt` is copied and `pip install` runs *before* `COPY . .`. In the common case (code change, no dependency change) the pip layer is correctly reused. `--no-cache` is the explicit escape hatch for the edge case where Docker's cache key is stale.
