from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.account import Account
from app.schemas.account import AccountCreate


def get_accounts(db: Session, user_id: int) -> list[Account]:
    """Return every account owned by the given user, ordered by creation date.

    Filtering on user_id here (not in the router) keeps the ownership check
    in one place. If we ever add team accounts, this is the only function
    to update.
    """
    return (
        db.query(Account)
        .filter(Account.user_id == user_id)
        .order_by(Account.created_at.asc())
        .all()
    )


def get_account(db: Session, account_id: int, user_id: int) -> Account:
    """Return a single account, raising 404 if it doesn't exist or isn't owned by user.

    Combining the id and user_id filters in one query is both faster (single
    round-trip) and safer (no TOCTOU window between "does it exist?" and
    "does the user own it?").

    A missing account and an account owned by someone else both return 404 —
    returning 403 for the latter would confirm to an attacker that the account
    id exists, which is an information leak.
    """
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.user_id == user_id)
        .first()
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found",
        )
    return account


def create_account(
    db: Session, user_id: int, account_schema: AccountCreate
) -> Account:
    """Create a new account for the given user.

    balance is not accepted from the schema (it's absent from AccountCreate).
    New accounts always start at 0; the balance is maintained by
    update_account_balance() as transactions are recorded.
    """
    account = Account(
        user_id=user_id,
        name=account_schema.name,
        account_type=account_schema.account_type,
        currency=account_schema.currency,
        balance=Decimal("0"),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def update_account_balance(
    db: Session, account_id: int, amount_delta: Decimal
) -> Optional[Account]:
    """Add amount_delta to the account's balance atomically using SELECT FOR UPDATE.

    Why SELECT FOR UPDATE instead of a plain read-then-write?
    Without a lock, two concurrent requests (e.g. two transactions submitted
    at the same millisecond) could both read balance=1000, both compute
    1000 + their delta, and the second write silently discards the first
    delta — the "lost update" problem.

    SELECT FOR UPDATE acquires a row-level exclusive lock until the surrounding
    transaction commits or rolls back. Any other session trying to lock or
    modify the same row must wait, serialising the updates correctly.

    This function does NOT call db.commit(). The caller (create_transaction)
    is responsible for committing so that the transaction INSERT and the
    balance UPDATE land in the same atomic commit.
    """
    account = (
        db.query(Account)
        .filter(Account.id == account_id)
        .with_for_update()   # SELECT ... FOR UPDATE
        .first()
    )
    if account is None:
        return None

    # Keep arithmetic in Decimal to match the Numeric(12, 2) column type.
    # Casting account.balance (which psycopg2 returns as Decimal) through
    # str avoids any floating-point representation errors during addition.
    account.balance = Decimal(str(account.balance)) + amount_delta
    # flush() pushes the UPDATE to Postgres within the current transaction
    # without committing, so the caller's subsequent INSERT is in the same tx.
    db.flush()
    return account
