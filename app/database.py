from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()

# ── Engine ────────────────────────────────────────────────────────────────────
# The engine is the entry point for all database communication. SQLAlchemy
# maintains a connection pool internally; by default it keeps up to 5 idle
# connections open so each request doesn't pay a TCP handshake cost.
#
# check_same_thread=False is only needed for SQLite (where it's the default
# restriction). We set it here as a comment reminder — it's NOT required for
# Postgres and is omitted accordingly.
engine = create_engine(
    settings.DATABASE_URL,
    # echo=True would log every SQL statement — useful during development but
    # too noisy for production. Controlled here rather than in uvicorn logging.
    echo=False,
    # pool_pre_ping sends a lightweight SELECT 1 before handing a pooled
    # connection to the caller. This detects stale connections that were dropped
    # by the DB server (e.g. after a restart) and transparently reconnects.
    pool_pre_ping=True,
)

# ── Session factory ───────────────────────────────────────────────────────────
# sessionmaker creates a reusable factory for Session objects.
#   autocommit=False — we control transaction boundaries explicitly via
#                      session.commit() / session.rollback(). Never use
#                      autocommit=True; it breaks atomic multi-step operations.
#   autoflush=False  — SQLAlchemy won't automatically flush pending changes to
#                      the DB before each query. This avoids surprise round-
#                      trips and gives us full control of when SQL is emitted.
#   bind=engine      — every session produced by this factory uses our engine.
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# ── Declarative base ──────────────────────────────────────────────────────────
# All ORM model classes inherit from Base. SQLAlchemy uses this shared base to
# track the complete set of mapped tables, which Alembic reads via
# Base.metadata when generating migration scripts.
class Base(DeclarativeBase):
    pass


# ── FastAPI dependency ────────────────────────────────────────────────────────
def get_db():
    """Yield a database session for the duration of a single HTTP request.

    Usage in a route:
        @router.get("/items")
        def list_items(db: Session = Depends(get_db)):
            return db.query(Item).all()

    The try/finally pattern guarantees the session is closed even if the
    route handler raises an exception. Closing returns the underlying
    connection back to the pool rather than destroying it.

    We deliberately do NOT call db.commit() here; each route is responsible
    for committing its own transaction. This prevents partial writes from
    being committed if only part of a multi-step operation succeeds.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
