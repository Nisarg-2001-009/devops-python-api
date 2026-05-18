# Service layer package.
# Each module owns the business logic for one domain entity.
# Routers call into services; services call into the database layer.
# No SQLAlchemy imports belong in routers — keep that boundary clean.
