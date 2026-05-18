from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth.security import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.account import AccountCreate, AccountResponse
from app.services import account_service

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get(
    "",
    response_model=list[AccountResponse],
    summary="List all accounts for the current user",
)
def list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all accounts owned by the authenticated user.

    The authenticated user's id is read from the JWT via get_current_user —
    not from a query parameter. This makes it impossible for a user to request
    another user's accounts by passing a different id in the URL.
    """
    return account_service.get_accounts(db, current_user.id)


@router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
def create_account(
    account_schema: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new account linked to the current user.

    user_id is injected from the JWT, not accepted from the request body —
    a client cannot create an account on behalf of another user.
    """
    return account_service.create_account(db, current_user.id, account_schema)


@router.get(
    "/{account_id}",
    response_model=AccountResponse,
    summary="Get a single account by ID",
)
def get_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a single account, 404 if it doesn't exist or isn't owned by the caller.

    The ownership check is inside account_service.get_account(), not here,
    so the logic is in one place and cannot be accidentally bypassed by a
    future refactor of this route.
    """
    return account_service.get_account(db, account_id, current_user.id)
