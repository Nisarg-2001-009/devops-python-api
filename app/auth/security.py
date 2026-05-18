from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import bcrypt
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.schemas.user import TokenData

settings = get_settings()

# ── Password hashing ──────────────────────────────────────────────────────────
# Using the bcrypt library directly instead of passlib's CryptContext wrapper.
# passlib ≥ 1.7.4 has a known bug where its internal wrap-detection test calls
# hashpw() with a 72-byte sentinel and crashes on bcrypt ≥ 4.x, which enforces
# the 72-byte limit strictly. Bypassing passlib removes the problematic layer
# while keeping identical security properties:
#   - bcrypt.gensalt() generates a random 16-byte salt per hash (work factor 12)
#   - bcrypt.checkpw() uses constant-time comparison — timing-safe by design

# ── OAuth2 bearer token extraction ────────────────────────────────────────────
# OAuth2PasswordBearer tells FastAPI:
#   1. That this API uses the OAuth2 "password" flow (username + password → token)
#   2. Where clients should POST to get a token (used in OpenAPI docs UI)
#   3. How to extract the token from incoming requests:
#      it reads the "Authorization: Bearer <token>" header automatically.
#
# auto_error=True (default): if the header is missing FastAPI raises 401
# immediately, before our dependency even runs.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Password helpers ──────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    """Return a bcrypt hash of the plain-text password.

    Never store or log the plain-text value. Call this exactly once, at
    registration time, and persist only the returned hash.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if plain_password matches the stored bcrypt hash.

    bcrypt embeds the salt and cost factor in the hash string itself, so
    callers don't need to manage those details. checkpw() is constant-time,
    preventing timing attacks that could reveal whether a hash prefix matches.
    """
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


# ── JWT creation ──────────────────────────────────────────────────────────────
def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Sign and return a JWT containing the given claims.

    Args:
        data:         Claims to embed. Typically {"sub": user.email}.
                      Do NOT include sensitive data (passwords, credit cards)
                      — JWTs are base64-encoded, not encrypted; anyone with the
                      token can decode the payload.
        expires_delta: Override the default expiry. Pass timedelta(minutes=5)
                       for short-lived tokens (e.g. password-reset links).

    Returns:
        A compact, URL-safe JWT string: header.payload.signature

    The 'exp' claim is verified automatically by python-jose on decode —
    expired tokens raise JWTError, which get_current_user converts to 401.
    """
    payload = data.copy()

    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    # 'exp' is a reserved JWT claim (RFC 7519 §4.1.4). python-jose validates
    # it automatically when decoding — we don't need a manual expiry check.
    payload["exp"] = expire

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


# ── FastAPI authentication dependency ─────────────────────────────────────────

# A single reusable exception keeps the 401 response consistent across every
# endpoint that uses get_current_user. WWW-Authenticate is required by RFC 6750
# (Bearer Token Usage) — some clients won't retry auth without it.
_credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Decode the JWT and return the corresponding User row from the database.

    This function is designed to be used as a FastAPI dependency:

        @router.get("/me")
        def read_me(current_user: User = Depends(get_current_user)):
            return current_user

    Raises HTTP 401 in every failure case (missing token, invalid signature,
    expired token, unknown user, inactive user) — we deliberately do not
    distinguish between them to avoid leaking information about valid emails.

    Flow:
        1. oauth2_scheme extracts the Bearer token from the Authorization header.
        2. jwt.decode() verifies the signature with SECRET_KEY and checks 'exp'.
        3. We read the 'sub' claim (email) and look up the user in the DB.
        4. We verify the account is still active.
        5. We return the ORM User object — route handlers receive it directly.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        # 'sub' (subject) is the standard JWT claim for the principal identity.
        email: Optional[str] = payload.get("sub")
        if email is None:
            raise _credentials_exception

        token_data = TokenData(email=email)

    except JWTError:
        # Covers: invalid signature, expired token, malformed token.
        # We re-raise as 401 rather than 500 — it's always the client's fault.
        raise _credentials_exception

    user = db.query(User).filter(User.email == token_data.email).first()
    if user is None:
        # The token was valid but references a deleted account.
        raise _credentials_exception

    if not user.is_active:
        # Account exists but has been soft-disabled by an admin.
        # Raise 401 (not 403) to avoid revealing that the account exists.
        raise _credentials_exception

    return user
