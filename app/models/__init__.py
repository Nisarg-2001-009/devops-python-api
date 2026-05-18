# This file serves two purposes:
#
# 1. Alembic discovery — when env.py does `from app.models import *` (or simply
#    imports this package), every model class is imported into the same Python
#    process, so their __tablename__ and Column definitions are registered on
#    Base.metadata. Alembic reads Base.metadata to generate migration scripts.
#    If a model file is not imported here, Alembic will not see its table and
#    will generate a DROP TABLE statement for it on the next autogenerate run.
#
# 2. Relationship resolution — SQLAlchemy resolves string-based relationship
#    targets (e.g. relationship("Account")) lazily at mapper configuration time.
#    All referenced classes must be importable from the same metadata registry.
#    Importing every model here guarantees they are all present before any
#    mapper configuration fires.

from app.models.account import Account  # noqa: F401
from app.models.budget import Budget  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.transaction import Transaction  # noqa: F401
from app.models.user import User  # noqa: F401

# ── Back-references wired via relationship() on child models ──────────────────
# User.accounts     → Account.user        (defined in account.py)
# User.categories   → Category.user       (defined in category.py)
# User.budgets      → Budget.user         (defined in budget.py)
# Account.transactions → Transaction.account (defined in transaction.py)
# Category.transactions → Transaction.category (defined in transaction.py)
# Category.budgets  → Budget.category     (defined in budget.py)
#
# All back_populates attributes are validated at startup; a typo raises
# InvalidRequestError immediately rather than silently returning wrong data.

__all__ = ["User", "Account", "Category", "Transaction", "Budget"]
