from typing import Optional

from sqlalchemy.orm import Session

from app.auth.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Return the User row matching email, or None if not found.

    The email column has a unique index (declared in the model), so this
    query always does an index scan rather than a full-table sequential scan.
    Using .first() instead of .one() avoids raising NoResultFound when the
    user doesn't exist — None is easier to branch on than an exception.
    """
    return db.query(User).filter(User.email == email).first()


def create_user(db: Session, user_schema: UserCreate) -> User:
    """Persist a new user, hashing the plain-text password before saving.

    The caller is responsible for verifying that the email is not already
    taken before calling this function (to surface a clean 409 rather than
    letting a DB IntegrityError bubble up as a 500).

    Flow:
      1. Hash the password — the plain-text value never touches the database.
      2. Construct the ORM object with only the fields that belong in the DB.
      3. add() stages the INSERT; commit() writes it and refreshes the object
         so that server-generated fields (id, created_at) are populated.
    """
    hashed = hash_password(user_schema.password)
    user = User(email=user_schema.email, hashed_password=hashed)
    db.add(user)
    db.commit()
    # refresh() re-reads the row from the DB so the caller gets the auto-
    # generated id and created_at values rather than Python-side defaults.
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """Return the User if credentials are valid, otherwise return None.

    Returning None (instead of raising an exception) keeps the calling
    code simple: the router checks `if not user` and raises 401 itself.

    verify_password() uses bcrypt's constant-time comparison, so the
    response time is the same whether the email exists or not — timing
    attacks cannot distinguish between "wrong email" and "wrong password".
    """
    user = get_user_by_email(db, email)
    if user is None:
        # Run a dummy verification to keep response time constant and
        # prevent timing-based email enumeration attacks.
        verify_password(password, "$2b$12$dummyhashtopreventtimingattacks000000000000000")
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user
