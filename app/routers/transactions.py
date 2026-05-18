from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth.security import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.transaction import TransactionCreate, TransactionResponse
from app.services import transaction_service

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _build_response(transaction) -> TransactionResponse:
    """Construct TransactionResponse, injecting the denormalised category_name.

    TransactionResponse.model_validate() reads ORM attributes via
    from_attributes=True, but category_name is not an ORM column — it's a
    convenience field we fill from the eagerly loaded relationship.
    We model_dump() → mutate → re-validate so Pydantic runs its validators
    on the final dict (e.g. ensuring Decimal precision is preserved).
    """
    data = TransactionResponse.model_validate(transaction).model_dump()
    data["category_name"] = (
        transaction.category.name if transaction.category else None
    )
    return TransactionResponse.model_validate(data)


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new transaction",
)
def create_transaction(
    transaction_schema: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a transaction and atomically update the account balance.

    The service verifies that account_id and category_id (if provided) belong
    to current_user before inserting. The balance update and transaction INSERT
    share a single db.commit() so they are atomic.
    """
    transaction = transaction_service.create_transaction(
        db, current_user.id, transaction_schema
    )
    return _build_response(transaction)


@router.get(
    "",
    response_model=list[TransactionResponse],
    summary="List transactions with optional filters",
)
def list_transactions(
    # Pagination
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=20, ge=1, le=200, description="Max records to return"),
    # Optional filters — all are None by default (no filter applied)
    category_id: Optional[int] = Query(default=None, description="Filter by category"),
    account_id: Optional[int] = Query(default=None, description="Filter by account"),
    start_date: Optional[date] = Query(default=None, description="Earliest transaction date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(default=None, description="Latest transaction date (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a filtered, paginated list of transactions for the current user.

    All query parameters are optional — omitting them returns all transactions
    in reverse chronological order. Combine them freely:
      GET /transactions?account_id=3&start_date=2025-01-01&end_date=2025-01-31

    The service builds the WHERE clause dynamically from whichever filters are
    non-None, so only the provided filters affect the query.
    """
    transactions = transaction_service.get_transactions(
        db,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
        category_id=category_id,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
    )
    return [_build_response(t) for t in transactions]


@router.get(
    "/{transaction_id}",
    response_model=TransactionResponse,
    summary="Get a single transaction by ID",
)
def get_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a single transaction. 404 if not found or not owned by the caller."""
    transaction = transaction_service.get_transaction(db, transaction_id, current_user.id)
    return _build_response(transaction)


@router.delete(
    "/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a transaction and reverse its balance effect",
)
def delete_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a transaction and atomically reverse the account balance update.

    HTTP 204 No Content is the correct response for a successful DELETE —
    there is no body to return. FastAPI enforces this: if the function returns
    a value with status_code=204, it is silently discarded.
    """
    transaction_service.delete_transaction(db, transaction_id, current_user.id)
