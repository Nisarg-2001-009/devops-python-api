from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Account(Base):
    """A financial account belonging to a user (bank, credit card, cash wallet, etc.).

    Each account tracks its own running balance in a chosen currency. Balances
    are stored as Numeric (exact decimal) rather than Float to avoid the
    floating-point rounding errors that accumulate in financial calculations.
    """

    __tablename__ = "accounts"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ── Ownership ─────────────────────────────────────────────────────────────
    # ondelete="CASCADE" tells Postgres to automatically delete all accounts when
    # the parent user row is deleted — no orphaned rows left behind.
    # The index on user_id makes "fetch all accounts for user X" fast.
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    # Human-readable label the user assigns, e.g. "HDFC Savings", "Cash Wallet".
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Controlled vocabulary for the account type. Using a plain String rather
    # than a Postgres ENUM keeps migrations simpler — adding a new type doesn't
    # require an ALTER TYPE statement. Validation of allowed values happens in
    # the Pydantic schema layer.
    # Expected values: checking | savings | credit | cash
    account_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # ── Balance ───────────────────────────────────────────────────────────────
    # Numeric(12, 2): up to 10 digits before the decimal and 2 after.
    # Maximum representable value: 9,999,999,999.99 — plenty for personal finance.
    # Credit card accounts may legitimately hold negative balances.
    balance: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )

    # ISO 4217 three-letter currency code (USD, EUR, INR, …).
    # Length 3 is exact for all standard codes; no index needed as filtering by
    # currency across accounts is uncommon.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    # ── Timestamp ─────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    # back_populates must match User.accounts attribute name.
    user: Mapped["User"] = relationship("User", back_populates="accounts")  # noqa: F821

    # cascade="all, delete-orphan" — deleting an account automatically removes
    # all its transactions, preventing orphaned transaction rows.
    transactions: Mapped[list["Transaction"]] = relationship(  # noqa: F821
        "Transaction", back_populates="account", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Account id={self.id} name={self.name!r} type={self.account_type!r}>"
