from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application-wide configuration driven entirely by environment variables.

    Pydantic's BaseSettings reads values in this priority order:
      1. Fields passed directly when instantiating Settings()
      2. Environment variables (case-insensitive match to field names)
      3. Variables loaded from the .env file (via model_config below)
      4. Field default values declared here

    This means the same class works in every environment — local dev (.env file),
    Docker (environment: block in docker-compose.yml), and CI/CD (injected secrets)
    without any code changes.
    """

    # ── Database ──────────────────────────────────────────────────────────────
    # Full SQLAlchemy connection string. The format is:
    #   postgresql://<user>:<password>@<host>:<port>/<database>
    # No default is intentional — the app should fail fast if this is missing.
    DATABASE_URL: str

    # ── JWT / security ────────────────────────────────────────────────────────
    # Used as the HMAC signing key for JWT tokens. Must be kept secret and should
    # be at least 32 random characters. Generate with: openssl rand -hex 32
    SECRET_KEY: str

    # Signing algorithm for python-jose. HS256 (HMAC-SHA256) is symmetric and
    # appropriate for a single-service setup. Switch to RS256 if multiple services
    # need to verify tokens without sharing the private key.
    ALGORITHM: str = "HS256"

    # How long an access token remains valid after issuance (in minutes).
    # 30 min is a balanced default; tighten for sensitive apps, relax for UX.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ── Application metadata ──────────────────────────────────────────────────
    # Surfaced in the OpenAPI docs title and /health endpoint responses.
    APP_NAME: str = "Finance Tracker API"
    VERSION: str = "1.0.0"

    model_config = {
        # Tell Pydantic to also look for variables in a .env file.
        # If the file is absent, Pydantic silently skips it — no error.
        "env_file": ".env",
        # Ignore extra keys in the .env that aren't declared as fields.
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    """Return the application Settings instance, cached after the first call.

    lru_cache ensures the .env file is read and validated exactly once per
    process lifetime, no matter how many times get_settings() is called.
    This makes it safe (and cheap) to use as a FastAPI dependency:

        @router.get("/")
        def read_root(settings: Settings = Depends(get_settings)):
            ...

    In tests, call get_settings.cache_clear() before overriding env vars so
    the cache doesn't return stale values from a previous test.
    """
    return Settings()
