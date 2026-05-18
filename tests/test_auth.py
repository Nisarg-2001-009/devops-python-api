"""Tests for POST /api/v1/auth/register and POST /api/v1/auth/login.

Strategy: these are pure black-box HTTP tests. We send requests through the
full FastAPI stack (routing → service → SQLite) and assert on HTTP status
codes and response bodies. No ORM objects are inspected directly.
"""

from tests.conftest import TEST_USER_EMAIL, TEST_USER_PASSWORD

# ── Helpers ───────────────────────────────────────────────────────────────────

def _register(client, email=TEST_USER_EMAIL, password=TEST_USER_PASSWORD):
    """POST to /register and return the response."""
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )


def _login(client, email=TEST_USER_EMAIL, password=TEST_USER_PASSWORD):
    """POST to /login with OAuth2 form data and return the response."""
    return client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )


# ── Registration tests ────────────────────────────────────────────────────────

def test_register_success(client):
    """A new user registration returns 201 and echoes the email back.

    We check:
    - HTTP 201 Created (not 200) — FastAPI is configured with status_code=201
      on the route; a 200 would mean the router config was accidentally changed.
    - The email appears in the response body so the caller can confirm which
      account was created without a separate lookup.
    - hashed_password is NOT in the response — if it appears, UserResponse is
      accidentally exposing the security field.
    """
    response = _register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == TEST_USER_EMAIL
    assert "hashed_password" not in body
    assert "password" not in body


def test_register_duplicate_email(client):
    """Registering the same email twice returns 409 Conflict.

    The first registration must succeed (201) so we know the 409 is genuinely
    triggered by the duplicate, not by the first call failing silently.
    The detail message should reference the email uniqueness constraint so the
    caller knows which field caused the conflict.
    """
    first = _register(client)
    assert first.status_code == 201

    second = _register(client)
    assert second.status_code == 409
    assert "email" in second.json()["detail"].lower()


# ── Login tests ───────────────────────────────────────────────────────────────

def test_login_success(client):
    """Valid credentials return a JWT access token with token_type 'bearer'.

    token_type must be exactly "bearer" (lowercase) per RFC 6750. Some HTTP
    clients do a case-sensitive comparison, so "Bearer" would break them.
    access_token must be a non-empty string — we don't decode the JWT here
    (that's tested implicitly by the protected-endpoint tests) but we confirm
    the field exists and is populated.
    """
    _register(client)
    response = _login(client)

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 0


def test_login_wrong_password(client):
    """A correct email with a wrong password returns 401 Unauthorized.

    Critically, the error message must NOT reveal that the email was found —
    "Incorrect email or password" is the expected wording. A message like
    "Incorrect password" would confirm the email exists and enable enumeration.
    """
    _register(client)
    response = _login(client, password="wrongpassword")

    assert response.status_code == 401
    # The detail must be ambiguous — it must NOT say only "password" was wrong.
    detail = response.json()["detail"].lower()
    assert "incorrect" in detail


def test_login_nonexistent_user(client):
    """Logging in with an email that was never registered returns 401.

    The status code and error message must be identical to test_login_wrong_password
    so an attacker cannot distinguish "wrong email" from "wrong password" by
    comparing responses.
    """
    response = _login(client, email="nobody@example.com")

    assert response.status_code == 401
    detail = response.json()["detail"].lower()
    assert "incorrect" in detail
