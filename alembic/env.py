"""Alembic migration environment.

This file is executed by every `alembic` CLI command. It is responsible for:
  1. Making the application's Python packages importable.
  2. Loading environment variables from .env so the DB URL is available.
  3. Pointing Alembic at the SQLAlchemy metadata so autogenerate can diff
     the ORM models against the live database schema.
  4. Providing online (connected) and offline (SQL-script) migration modes.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── 1. Project root on sys.path ───────────────────────────────────────────────
# __file__ is  <project_root>/alembic/env.py
# .parent      is  <project_root>/alembic/
# .parent.parent is <project_root>/
# Inserting the project root at index 0 ensures "from app.X import Y" resolves
# even when alembic is invoked from outside the project root (e.g. in CI).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 2. Load .env ──────────────────────────────────────────────────────────────
# load_dotenv() reads key=value pairs from the .env file and adds them to
# os.environ. It must run BEFORE any app import that triggers pydantic_settings,
# because BaseSettings reads os.environ at class construction time (which
# happens when app.config is imported).
#
# override=False (the default) means existing env vars take precedence over
# the .env file — so CI/CD injected secrets are never silently overridden.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

# ── 3. Import ORM metadata ────────────────────────────────────────────────────
# Importing app.models runs all model files, which registers every table's
# Column definitions on Base.metadata. Alembic reads Base.metadata during
# autogenerate to discover new, changed, or removed tables.
#
# If any model file is NOT imported here (directly or transitively), Alembic
# will not see its table and will generate "DROP TABLE" in the next autogenerate
# run — a silent, destructive mistake.
# Base is defined in app.database; importing app.models registers all table
# definitions on that Base by running each model file as a side-effect.
import app.models  # noqa: F401, E402 — side-effect import; registers all tables
from app.database import Base  # noqa: E402

target_metadata = Base.metadata

# ── 4. Alembic config object ──────────────────────────────────────────────────
# context.config wraps alembic.ini so we can read/override settings at runtime.
config = context.config

# Wire up Python's standard logging using the [loggers] section in alembic.ini.
# This gives us timestamped migration progress in the terminal.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── 5. Override database URL ──────────────────────────────────────────────────
# Overriding sqlalchemy.url at runtime (rather than hardcoding it in alembic.ini)
# means:
#   - The connection string lives in one place: .env (or the CI secret store).
#   - alembic.ini can be safely committed without leaking credentials.
#   - Different environments (dev / staging / prod) just swap the .env file.
#
# os.environ["DATABASE_URL"] raises KeyError if the variable is missing, which
# surfaces a clear error instead of silently connecting to the wrong database.
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])


# ── Migration runners ─────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """Generate a SQL script without connecting to the database ('offline' mode).

    Used when you want to review or apply migrations manually:
        alembic upgrade head --sql > migration.sql

    literal_binds=True renders bound parameters as literal SQL values in the
    output script, making it human-readable and directly executable via psql.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # compare_type=True tells Alembic to detect column type changes
        # (e.g. String(100) → String(255)) during autogenerate.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database ('online' mode).

    pool.NullPool disables connection pooling for the migration process.
    Migrations run as one-off operations — a persistent pool would waste
    connections and could mask errors from a half-applied migration.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type changes during autogenerate (e.g. Numeric scale).
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


# ── Entry point ───────────────────────────────────────────────────────────────
# Alembic sets is_offline_mode() based on whether --sql was passed to the CLI.
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
