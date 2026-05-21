"""
Custom Prometheus business metrics for the Personal Finance Tracker.
All metric definitions live here to avoid circular imports.
"""

from prometheus_client import Counter, Histogram, Gauge

# Transaction metrics
TRANSACTIONS_CREATED_TOTAL = Counter(
    name="finance_transactions_created_total",
    documentation="Total number of transactions successfully created.",
    labelnames=["transaction_type"],
)

TRANSACTIONS_DELETED_TOTAL = Counter(
    name="finance_transactions_deleted_total",
    documentation="Total number of transactions deleted.",
)

TRANSACTION_AMOUNT = Histogram(
    name="finance_transaction_amount_dollars",
    documentation="Distribution of transaction amounts in dollars.",
    labelnames=["transaction_type"],
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
)

TRANSACTIONS_FETCH_TOTAL = Counter(
    name="finance_transactions_fetch_total",
    documentation="Total number of times the transactions list endpoint was called.",
)

# User metrics
USERS_REGISTERED_TOTAL = Counter(
    name="finance_users_registered_total",
    documentation="Total number of users registered.",
)

ACTIVE_USERS = Gauge(
    name="finance_active_users",
    documentation="Current number of users who have recently logged in.",
)

USER_LOGIN_TOTAL = Counter(
    name="finance_user_login_total",
    documentation="Total number of successful logins.",
)

USER_LOGIN_FAILURES_TOTAL = Counter(
    name="finance_user_login_failures_total",
    documentation="Total number of failed login attempts.",
)

# DB and error metrics
DB_QUERY_DURATION = Histogram(
    name="finance_db_query_duration_seconds",
    documentation="Time spent on database operations in seconds.",
    labelnames=["operation"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

API_ERRORS_TOTAL = Counter(
    name="finance_api_errors_total",
    documentation="Total application-level errors.",
    labelnames=["error_type", "endpoint"],
)
