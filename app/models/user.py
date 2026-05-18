from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """Registered application user.

    Stores only authentication data. All financial data (accounts, transactions,
    budgets) is linked to this table via foreign keys, making it straightforward
    to delete all of a user's data in one cascading operation if needed.
    """

    __tablename__ = "users"

    # ── Primary key ───────────────────────────────────────────────────────────
    # Integer PKs are compact and index-friendly. If you later need globally
    # unique IDs across services, swap to UUID with server_default=text("gen_random_uuid()").
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ── Identity ──────────────────────────────────────────────────────────────
    # unique=True enforces one account per email at the DB level (not just app
    # level) — a duplicate INSERT raises IntegrityError before we even check.
    # index=True speeds up the lookup-by-email that happens on every login.
    # Length 255 matches the RFC 5321 maximum for the local part + domain.
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )

    # We never store the raw password — only the bcrypt hash produced by passlib.
    # bcrypt output is always 60 characters, but String(255) gives headroom if
    # the hashing scheme changes in the future.
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # ── Status ────────────────────────────────────────────────────────────────
    # Soft-disable an account without deleting rows. Inactive users can't log in
    # but their historical data is preserved for audit purposes.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Timestamps ────────────────────────────────────────────────────────────
    # default=datetime.utcnow (no parentheses) passes the *function* as the
    # default factory; SQLAlchemy calls it at INSERT time, not at import time.
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    # updated_at starts as NULL; application code sets it on every UPDATE so we
    # can see when a record was last modified without inspecting audit logs.
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    # back_populates="user" must match the attribute name on Account that points
    # back here. lazy="select" (the default) loads accounts in a separate query
    # when first accessed — acceptable for most routes. Use lazy="joined" on
    # routes that always need both user + accounts in one round-trip.
    accounts: Mapped[list["Account"]] = relationship(  # noqa: F821
        "Account", back_populates="user", cascade="all, delete-orphan"
    )
    categories: Mapped[list["Category"]] = relationship(  # noqa: F821
        "Category", back_populates="user", cascade="all, delete-orphan"
    )
    budgets: Mapped[list["Budget"]] = relationship(  # noqa: F821
        "Budget", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
