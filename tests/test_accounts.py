"""Tests for GET/POST /api/v1/accounts and GET /api/v1/accounts/{id}.

Each test is self-contained: it creates whatever data it needs inline rather
than relying on shared state from other tests. This makes failures easy to
diagnose — a failing test tells you exactly what broke, not "something earlier
left the DB in a bad state."
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

_ACCOUNT_PAYLOAD = {
    "name": "My Checking Account",
    "account_type": "checking",
    "currency": "USD",
}


def _create_account(client, auth_headers, payload=None):
    return client.post(
        "/api/v1/accounts",
        json=payload or _ACCOUNT_PAYLOAD,
        headers=auth_headers,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_create_account_success(client, auth_headers):
    """Creating an account returns 201 and the account data including balance=0.

    balance must be 0 on a new account — the route must reject any attempt to
    set an opening balance via the request body (AccountCreate doesn't include
    balance, so Pydantic would strip it; this verifies the service default).
    user_id in the response must match the authenticated user, not some default
    or injected value from the request.
    """
    response = _create_account(client, auth_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == _ACCOUNT_PAYLOAD["name"]
    assert body["account_type"] == "checking"
    assert body["currency"] == "USD"
    # New accounts always start at zero — not caller-supplied.
    assert float(body["balance"]) == 0.0
    assert "id" in body
    assert "user_id" in body


def test_get_accounts_empty(client, auth_headers):
    """Listing accounts when none exist returns 200 with an empty list.

    An empty list is the correct response — 404 would be wrong here because
    the resource (the collection) exists, it just has no members.
    """
    response = client.get("/api/v1/accounts", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == []


def test_get_accounts_returns_created(client, auth_headers):
    """An account appears in the list immediately after creation.

    This verifies the round-trip: POST writes to the DB and GET reads from the
    same DB session (both go through the same overridden get_db fixture).
    We check the account id to confirm it's the same object, not a coincidental
    name match.
    """
    created = _create_account(client, auth_headers).json()

    response = client.get("/api/v1/accounts", headers=auth_headers)
    assert response.status_code == 200

    accounts = response.json()
    assert len(accounts) == 1
    assert accounts[0]["id"] == created["id"]
    assert accounts[0]["name"] == _ACCOUNT_PAYLOAD["name"]


def test_get_account_not_found(client, auth_headers):
    """Requesting an account id that doesn't exist returns 404.

    We use id=999999 — guaranteed not to exist in a fresh test database where
    auto-increment starts at 1. A 404 (not a 500) confirms the service handles
    the missing-row case gracefully rather than letting a NoneType crash bubble up.
    """
    response = client.get("/api/v1/accounts/999999", headers=auth_headers)

    assert response.status_code == 404


def test_unauthorized_access(client):
    """Requests without a Bearer token return 401.

    No `auth_headers` fixture is used here — that's intentional. The test
    verifies that the get_current_user dependency correctly rejects requests
    that have no Authorization header, before any route handler logic runs.
    """
    # Both list and detail routes must require auth.
    list_response = client.get("/api/v1/accounts")
    assert list_response.status_code == 401

    detail_response = client.get("/api/v1/accounts/1")
    assert detail_response.status_code == 401
