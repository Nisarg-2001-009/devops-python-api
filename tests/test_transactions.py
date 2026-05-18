"""Tests for POST/GET/DELETE /api/v1/transactions.

Each test creates its own account (and second user where needed) to stay
fully self-contained. The account id is dynamic — we can't hard-code 1
because SQLite auto-increment can behave differently depending on prior
test execution order, even with table drops between tests.
"""

from datetime import date

from tests.conftest import TEST_USER_EMAIL, TEST_USER_PASSWORD

# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_account(client, auth_headers):
    """Create a checking account and return its JSON body."""
    resp = client.post(
        "/api/v1/accounts",
        json={"name": "Test Account", "account_type": "checking", "currency": "USD"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, f"Account creation failed: {resp.json()}"
    return resp.json()


def _create_transaction(client, auth_headers, account_id, amount=-50.00, tx_date=None):
    """Create a transaction and return its JSON body."""
    payload = {
        "account_id": account_id,
        "amount": amount,
        "description": "Test transaction",
        "transaction_date": str(tx_date or date.today()),
    }
    resp = client.post("/api/v1/transactions", json=payload, headers=auth_headers)
    assert resp.status_code == 201, f"Transaction creation failed: {resp.json()}"
    return resp.json()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_create_transaction_success(client, auth_headers):
    """Creating a transaction returns 201 and updates the account balance.

    The balance check is the key assertion: it verifies that create_transaction
    and update_account_balance both fired in the same atomic commit. A 201 with
    an unchanged balance would indicate the balance update was skipped or not
    committed.
    """
    account = _create_account(client, auth_headers)
    account_id = account["id"]
    initial_balance = float(account["balance"])  # 0.00

    tx = _create_transaction(client, auth_headers, account_id, amount=-75.50)

    assert tx["account_id"] == account_id
    assert float(tx["amount"]) == -75.50
    assert "id" in tx
    assert "created_at" in tx

    # Verify the account balance was updated atomically.
    updated_account = client.get(f"/api/v1/accounts/{account_id}", headers=auth_headers).json()
    assert float(updated_account["balance"]) == initial_balance + (-75.50)


def test_get_transactions_empty(client, auth_headers):
    """Listing transactions with no data returns 200 and an empty list."""
    response = client.get("/api/v1/transactions", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == []


def test_get_transactions_with_filters(client, auth_headers):
    """Optional query filters narrow the result set independently.

    We create two transactions on different dates and verify:
    - account_id filter: only returns transactions for that account.
    - start_date / end_date filters: exclude transactions outside the range.
    This checks that the service's SQLAlchemy query-chaining logic applies
    each filter correctly rather than ignoring them.
    """
    account = _create_account(client, auth_headers)
    account_id = account["id"]

    jan_tx = _create_transaction(
        client, auth_headers, account_id, amount=-20.00,
        tx_date=date(2025, 1, 15)
    )
    _create_transaction(
        client, auth_headers, account_id, amount=-30.00,
        tx_date=date(2025, 3, 10)
    )

    # account_id filter — both transactions belong to same account, so 2 returned.
    resp = client.get(
        f"/api/v1/transactions?account_id={account_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    # Date range filter — only the January transaction falls in this window.
    resp = client.get(
        "/api/v1/transactions?start_date=2025-01-01&end_date=2025-02-01",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["id"] == jan_tx["id"]


def test_delete_transaction_success(client, auth_headers):
    """Deleting a transaction returns 204 and reverses the account balance.

    204 No Content is the correct status for a successful DELETE — no body.
    The balance reversal check is the critical assertion: it confirms that
    delete_transaction applied the negation of the original amount in the same
    commit as the row deletion.
    """
    account = _create_account(client, auth_headers)
    account_id = account["id"]

    tx = _create_transaction(client, auth_headers, account_id, amount=-40.00)
    tx_id = tx["id"]

    # Balance after creation should be -40.00.
    balance_after_create = float(
        client.get(f"/api/v1/accounts/{account_id}", headers=auth_headers).json()["balance"]
    )
    assert balance_after_create == -40.00

    delete_resp = client.delete(f"/api/v1/transactions/{tx_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Balance should be restored to 0.00 after deletion.
    balance_after_delete = float(
        client.get(f"/api/v1/accounts/{account_id}", headers=auth_headers).json()["balance"]
    )
    assert balance_after_delete == 0.00

    # The transaction should no longer exist.
    get_resp = client.get(f"/api/v1/transactions/{tx_id}", headers=auth_headers)
    assert get_resp.status_code == 404


def test_delete_other_users_transaction(client, auth_headers):
    """A user cannot delete another user's transaction — receives 404.

    We return 404 (not 403) to avoid confirming to the attacker that the
    transaction id exists. From their perspective, the resource "doesn't exist"
    for them — which is the correct information-theoretic response.

    Setup: user A creates a transaction, user B tries to delete it.
    """
    # User A creates an account and transaction (auth_headers belongs to user A).
    account = _create_account(client, auth_headers)
    tx = _create_transaction(client, auth_headers, account["id"], amount=-10.00)
    tx_id = tx["id"]

    # Register and log in as user B.
    client.post(
        "/api/v1/auth/register",
        json={"email": "userB@example.com", "password": "passwordB123"},
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        data={"username": "userB@example.com", "password": "passwordB123"},
    )
    user_b_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    # User B attempts to delete user A's transaction.
    delete_resp = client.delete(f"/api/v1/transactions/{tx_id}", headers=user_b_headers)
    assert delete_resp.status_code == 404

    # User A's transaction must still exist.
    get_resp = client.get(f"/api/v1/transactions/{tx_id}", headers=auth_headers)
    assert get_resp.status_code == 200
