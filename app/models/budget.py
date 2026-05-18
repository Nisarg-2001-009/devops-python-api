from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Budget(Base):
    """Monthly spending target for a single category.

    One row represents "user X wants to spend no more than $Y on category Z
    during month M of year N". The unique constraint on (user_id, category_id,
    month, year) enforces one budget per category per calendar month — attempts
    to insert a duplicate raise IntegrityError before the application layer even
    needs to validate.
    """

    __tablename__ = "budgets"

    # ── Table-level constraints ───────────────────────────────────────────────
    # Declared here (not on a column) because UniqueConstraint spans multiple
    # columns. The name kwarg is optional but makes the constraint easily
    # identifiable in Postgres pg_constraint and Alembic diffs.
    __table_args__ = (
        UniqueConstraint(
            "user_id", "category_id", "month", "year",
            name="uq_budget_user_category_month_year",
        ),
    )

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ── Ownership ─────────────────────────────────────────────────────────────
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── Category link ─────────────────────────────────────────────────────────
    # ondelete="CASCADE": when a category is deleted its budgets are also removed.
    # A budget without a category has no meaning, so CASCADE is correct here
    # (unlike Transaction where SET NULL preserves history).
    category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Budget amount ─────────────────────────────────────────────────────────
    # The planned spend ceiling for the month. Stored as Numeric for the same
    # reason as Transaction.amount — no floating-point drift in comparisons.
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    # ── Period ────────────────────────────────────────────────────────────────
    # Storing month and year as separate integers (rather than a Date) avoids
    # ambiguity about which day of the month the budget "starts" and makes
    # filtering by month straightforward: WHERE month = 3 AND year = 2025.
    # Application layer must validate: 1 <= month <= 12.
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── Timestamp ─────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="budgets")  # noqa: F821
    category: Mapped["Category"] = relationship(  # noqa: F821
        "Category", back_populates="budgets"
    )

    def __repr__(self) -> str:
        return (
            f"<Budget id={self.id} user_id={self.user_id} "
            f"category_id={self.category_id} {self.month}/{self.year} "
            f"amount={self.amount}>"
        )
