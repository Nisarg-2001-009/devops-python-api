"""Shared pytest fixtures for the entire test suite.

Design decisions:
- SQLite (file-based at test.db) is used instead of PostgreSQL so the test
  suite runs without a running Docker stack. SQLAlchemy's ORM is dialect-
  agnostic, so all CRUD endpoints work identically. The analytics service uses
  PostgreSQL-specific SQL (window functions, EXTRACT) and is mocked separately
  in test_analytics.py.
- Every test gets a FRESH database: tables are created before each test
  function and dropped after, so no test can leak state into another.
- The FastAPI dependency get_db is overridden to inject the SQLite session.
  The rest of the app (auth, routing, Pydantic validation) is exercised as-is.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# ── Test database ─────────────────────────────────────────────────────────────
# File-based SQLite so every session shares the same on-disk state within a
# test. ":memory:" would require StaticPool to share across threads; a file
# avoids that complexity.
# check_same_thread=False is required because FastAPI's TestClient may hand
# the same connection to different threads internally.
SQLALCHEMY_TEST_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── Known test-user credentials ───────────────────────────────────────────────
# Module-level constants keep the values consistent across fixtures and tests
# without relying on hard-coded strings scattered through the files.
TEST_USER_EMAIL = "testuser@example.com"
TEST_USER_PASSWORD = "testpassword123"


# ── Core fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def client():
    """Yield a TestClient backed by a fresh SQLite database.

    Lifecycle:
      1. Create all ORM tables on the test engine.
      2. Override FastAPI's get_db dependency so every request uses a
         SQLite session instead of the PostgreSQL one defined in database.py.
      3. Yield the TestClient — the test runs here.
      4. Clear the dependency override so it doesn't bleed into other tests.
      5. Drop all tables so the next test starts with an empty schema.

    scope="function" means this entire lifecycle runs once per test function,
    giving each test its own isolated database state.
    """
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    # TestClient is used as a context manager so startup/shutdown lifespan
    # events (logging in main.py) are triggered correctly.
    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def auth_token(client):
    """Register a test user and return a valid JWT access token.

    Depends on `client` (not created separately) so both the registration and
    login requests go through the same overridden get_db session that the test
    itself will use — no cross-session state mismatch.

    Returns the raw token string. Use `auth_headers` for the Authorization
    header dict that endpoints expect.
    """
    # Register — ignore the response; we only care that the user now exists.
    client.post(
        "/api/v1/auth/register",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    # Login uses OAuth2 form-encoded body (not JSON) — required by
    # OAuth2PasswordRequestForm. The field name is "username" per the spec,
    # even though our application uses it as an email address.
    login_response = client.post(
        "/api/v1/auth/login",
        data={"username": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    return login_response.json()["access_token"]


@pytest.fixture(scope="function")
def auth_headers(auth_token):
    """Return the Authorization header dict for an authenticated request.

    Usage:
        response = client.get("/api/v1/accounts", headers=auth_headers)
    """
    return {"Authorization": f"Bearer {auth_token}"}
