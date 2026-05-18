from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Category(Base):
    """User-defined label for grouping transactions and setting budgets.

    Categories are per-user so each person can have a custom taxonomy
    (e.g. "Chai & Snacks" instead of just "Food"). The is_income flag
    separates income sources (salary, freelance) from expense categories,
    which drives the correct sign in summary calculations.
    """

    __tablename__ = "categories"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ── Ownership ─────────────────────────────────────────────────────────────
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # ── Display metadata ──────────────────────────────────────────────────────
    # CSS hex colour code for UI chips/badges, e.g. "#FF5733".
    # Length 7 covers the full #RRGGBB format; no alpha channel needed here.
    colour: Mapped[str | None] = mapped_column(String(7), nullable=True)

    # Icon identifier (e.g. a Material Icon name like "restaurant" or an emoji
    # shortcode). Kept as a plain string so the frontend can choose its own
    # icon library without DB schema changes.
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── Type flag ─────────────────────────────────────────────────────────────
    # False → expense category (the common case, hence the default).
    # True  → income category. Separating these avoids mixing salary with
    # groceries in budget reports.
    is_income: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Timestamp ─────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="categories")  # noqa: F821

    # nullable FK on Transaction (category_id is optional) so we use a plain
    # list here; SQLAlchemy handles the NULL FK gracefully.
    transactions: Mapped[list["Transaction"]] = relationship(  # noqa: F821
        "Transaction", back_populates="category"
    )

    # A category can have one budget entry per month/year combination.
    budgets: Mapped[list["Budget"]] = relationship(  # noqa: F821
        "Budget", back_populates="category", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Category id={self.id} name={self.name!r} income={self.is_income}>"
