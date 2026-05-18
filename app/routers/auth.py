from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth.security import create_access_token
from app.database import get_db
from app.schemas.user import Token, UserCreate, UserResponse
from app.services import user_service

# prefix="/auth" means all routes here are under /auth/...
# tags=["auth"] groups these endpoints together in the OpenAPI docs UI.
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
def register(user_schema: UserCreate, db: Session = Depends(get_db)):
    """Create a new user and return the created user object.

    We check for duplicate email before inserting rather than relying solely
    on the DB unique constraint, because:
      - A caught IntegrityError produces a generic 500 without this guard.
      - We can surface a descriptive 409 Conflict message to the client.

    Note: returning UserResponse (not Token) so the client must call /login
    after registration. This keeps registration and authentication as separate
    concerns and allows email verification workflows in the future.
    """
    existing = user_service.get_user_by_email(db, user_schema.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )
    return user_service.create_user(db, user_schema)


@router.post(
    "/login",
    response_model=Token,
    summary="Obtain a JWT access token",
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Authenticate with email + password and receive a JWT access token.

    OAuth2PasswordRequestForm reads username and password from an
    application/x-www-form-urlencoded body (not JSON). This matches the
    OAuth2 spec and is required for the OpenAPI docs "Authorize" button to
    work. The 'username' field contains the email address.

    We embed the user's email as the 'sub' (subject) claim in the token.
    The 'sub' claim is the standard JWT field for the principal's identity
    (RFC 7519 §4.1.2). Embedding only the email (not the full user object)
    keeps token size small and avoids stale data — user details are always
    looked up fresh from the DB in get_current_user().
    """
    user = user_service.authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        # Always 401 — never reveal whether the email exists or the password
        # was wrong. Both cases look identical to the caller.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(data={"sub": user.email})
    return Token(access_token=token)
