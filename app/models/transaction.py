from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Transaction(Base):
    """A single money movement (debit or credit) against an account.

    Sign convention: positive amount = money in (income / refund),
    negative amount = money out (expense). Enforcing this at the model
    level keeps all aggregate queries consistent — SUM(amount) always gives
    the net change to the account balance over any period.
    """

    __tablename__ = "transactions"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ── Foreign keys ─────────────────────────────────────────────────────────
    # Every transaction must belong to an account. Deleting the account
    # cascades here via Account.transactions relationship (cascade="all, delete-orphan").
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # Indexed: most queries filter by account
    )

    # Category is optional — users may log a transaction before categorising it
    # (e.g. a pending charge). SET NULL on delete keeps the transaction row
    # intact when a category is removed.
    category_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Core fields ───────────────────────────────────────────────────────────
    # Numeric(12, 2) for exact decimal arithmetic — floats accumulate rounding
    # errors over thousands of transactions.
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    # Optional memo / payee name. 500 chars covers long merchant descriptions
    # while staying well within Postgres' inline-storage threshold (~2 KB).
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Date (not DateTime) because the exact time of a transaction is rarely
    # available from bank exports and is not needed for monthly reporting.
    # Indexed to speed up date-range queries like "transactions in March".
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # ── Timestamp ─────────────────────────────────────────────────────────────
    # created_at records when the row was inserted into our system, which differs
    # from transaction_date (the actual transaction date as reported by the bank).
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    account: Mapped["Account"] = relationship(  # noqa: F821
        "Account", back_populates="transactions"
    )

    # category can be None when category_id is NULL.
    category: Mapped["Category | None"] = relationship(  # noqa: F821
        "Category", back_populates="transactions"
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} amount={self.amount} "
            f"date={self.transaction_date}>"
        )
