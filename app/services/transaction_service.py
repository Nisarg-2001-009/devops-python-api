from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.account import Account
from app.models.transaction import Transaction
from app.schemas.transaction import TransactionCreate
from app.services.account_service import get_account, update_account_balance


def get_transaction(db: Session, transaction_id: int, user_id: int) -> Transaction:
    """Return a single transaction with its category eagerly loaded.

    Ownership is verified by joining to accounts — a transaction belongs to
    a user only if its account belongs to that user. Filtering on both
    transaction id and account.user_id in one query avoids a TOCTOU window.

    joinedload(Transaction.category) tells SQLAlchemy to JOIN categories in
    the same query rather than issuing a second SELECT when we access
    transaction.category — prevents an N+1 query when the router accesses
    category.name for the response.
    """
    transaction = (
        db.query(Transaction)
        .options(joinedload(Transaction.category))
        .join(Account, Transaction.account_id == Account.id)
        .filter(Transaction.id == transaction_id, Account.user_id == user_id)
        .first()
    )
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {transaction_id} not found",
        )
    return transaction


def get_transactions(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
    category_id: Optional[int] = None,
    account_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[Transaction]:
    """Return a paginated, optionally filtered list of transactions.

    Query chaining — building the query incrementally with if-blocks —
    lets us add filters without duplicating the base query. SQLAlchemy
    doesn't execute anything until .all() is called, so chaining is free.

    All filters respect user ownership through the mandatory JOIN on accounts.
    A user cannot view transactions from another user's account by guessing
    an account_id, because the `Account.user_id == user_id` filter will
    exclude rows they don't own.

    Pagination: skip/limit implement OFFSET/LIMIT. For large datasets,
    keyset pagination (WHERE id > last_seen_id) scales better, but
    offset pagination is simpler and sufficient for personal finance data.
    """
    # Base query: join to accounts to enforce ownership.
    # joinedload for category avoids N+1 when serialising the response list.
    query = (
        db.query(Transaction)
        .options(joinedload(Transaction.category))
        .join(Account, Transaction.account_id == Account.id)
        .filter(Account.user_id == user_id)
    )

    # Each filter is appended only if the caller supplied it.
    # None means "no filter"; 0 would be a valid value so we check `is not None`.
    if category_id is not None:
        query = query.filter(Transaction.category_id == category_id)

    if account_id is not None:
        # Extra ownership check: verify this account belongs to the user.
        # The JOIN above already filters by user_id, but being explicit here
        # makes the intent clear and keeps security logic in one location.
        query = query.filter(Transaction.account_id == account_id)

    if start_date is not None:
        query = query.filter(Transaction.transaction_date >= start_date)

    if end_date is not None:
        query = query.filter(Transaction.transaction_date <= end_date)

    return (
        query
        .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def create_transaction(
    db: Session, user_id: int, transaction_schema: TransactionCreate
) -> Transaction:
    """Create a transaction and update the account balance in one atomic commit.

    Atomicity is the critical requirement here: we must never have a
    transaction row without the corresponding balance update (or vice versa).
    By calling db.commit() once after both the INSERT and the UPDATE are
    staged, either both land or neither does.

    update_account_balance() uses SELECT FOR UPDATE to lock the account row
    before modifying it, preventing concurrent requests from producing a
    lost-update race condition on the balance column.

    Ownership of account_id is verified by get_account() — it raises 404 if
    the account doesn't exist or belongs to another user. This prevents a
    malicious user from recording transactions against accounts they don't own.
    """
    # Raises 404 if account doesn't exist or is owned by someone else.
    get_account(db, transaction_schema.account_id, user_id)

    # Verify category_id (if provided) belongs to this user.
    # Without this check, a user could categorise their transactions under
    # another user's custom categories, revealing that those categories exist.
    if transaction_schema.category_id is not None:
        from app.models.category import Category
        category = (
            db.query(Category)
            .filter(
                Category.id == transaction_schema.category_id,
                Category.user_id == user_id,
            )
            .first()
        )
        if category is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category {transaction_schema.category_id} not found",
            )

    transaction = Transaction(
        account_id=transaction_schema.account_id,
        category_id=transaction_schema.category_id,
        amount=transaction_schema.amount,
        description=transaction_schema.description,
        transaction_date=transaction_schema.transaction_date,
    )
    db.add(transaction)

    # Stage the balance update in the same transaction. flush() pushes the
    # INSERT and the UPDATE to Postgres but does not commit — they share the
    # same transaction boundary.
    update_account_balance(
        db,
        account_id=transaction_schema.account_id,
        amount_delta=Decimal(str(transaction_schema.amount)),
    )

    # Single commit: both the transaction row and the balance change are
    # durable together. If the process crashes here, Postgres rolls back both.
    db.commit()
    db.refresh(transaction)

    # Eagerly load category after refresh so the router can access category.name
    # without triggering another query on an expired session attribute.
    db.query(Transaction).options(joinedload(Transaction.category)).filter(
        Transaction.id == transaction.id
    ).first()

    return transaction


def delete_transaction(db: Session, transaction_id: int, user_id: int) -> None:
    """Delete a transaction and reverse its effect on the account balance atomically.

    We reverse by applying the negation of the original amount — if the
    transaction was -50 (an expense), the reversal is +50 (balance goes back up).
    This is the same path as create_transaction, just with the sign flipped.

    As with create, the DELETE and balance reversal share one db.commit().
    """
    transaction = get_transaction(db, transaction_id, user_id)

    # Reverse the balance impact before deleting the transaction row.
    # The order matters: update_account_balance needs the account_id from the
    # transaction object, which is gone after db.delete() + db.flush().
    reversal_amount = Decimal(str(transaction.amount)) * -1
    update_account_balance(db, transaction.account_id, reversal_amount)

    db.delete(transaction)
    db.commit()
