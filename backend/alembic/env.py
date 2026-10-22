"""Alembic environment for the operational store.

Two things are deliberate here.

**The URL comes from `settings`, not from alembic.ini.** `DATABASE_URL` is the
one knob that decides where cases live (convention 1), and a second copy of it
in an ini file is a copy that drifts. `alembic.ini` carries no `sqlalchemy.url`
at all, so there is nothing to drift from.

**The metadata is the application's own `Base`.** Autogenerate therefore compares
migrations against the models the code actually uses, which is what makes the
test in `test_migrations.py` meaningful: a migrated database and a
`create_all` database must end up with the same schema, or one of them is lying.

`get_engine()` still calls `create_all`, and that stays. Migrations are for an
operator moving an existing store forward - and for the Postgres swap D-09
promises, where `create_all` on a shared database is not an acceptable answer.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spendguard.config import settings  # noqa: E402
from spendguard.db.store import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Only when the caller has not already chosen one. A test, or an operator
# migrating a second store, passes `-x` or sets it on the Config object, and
# an unconditional override here would quietly send those migrations to the
# default store instead - which is how the first run of this file created
# tables in the live database rather than the temporary one.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without a connection, for review before it is applied."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER most things in place; batch mode rewrites the
        # table instead. Harmless on Postgres, essential here.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection", None)
    if connectable is None:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:  # noqa: ANN001
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
