"""Alembic environment. Schema changes only through revisions, never create_all."""

from alembic import context
from sqlalchemy import create_engine, pool

from cine_analyzer.adapters.persistence.tables import Base
from cine_analyzer.settings import load_settings

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    settings = load_settings()
    if settings.database_url is None:
        message = "CINE_DATABASE_URL is required to run migrations"
        raise RuntimeError(message)
    return settings.database_url


def run_migrations_offline() -> None:
    """Emit SQL without a live connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against PostgreSQL."""
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
