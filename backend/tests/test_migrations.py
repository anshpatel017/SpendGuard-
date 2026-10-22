"""Alembic migrations against the operational store (NFR-10).

The store builds its own tables through ``Base.metadata.create_all`` on every
connection, and that stays - it is what makes a fresh clone work with no setup
step. Migrations exist for the other two cases: moving an *existing* store
forward, and the Postgres swap D-09 promises, where letting an application call
``create_all`` against a shared database is not an acceptable answer.

Two schemas therefore describe the same store, which is exactly the situation
where they drift. The test that matters is not "migrations run" but "migrations
and the models agree", so that is the one written here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from spendguard.db.store import Base

BACKEND = Path(__file__).resolve().parents[1]


def _alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _shape(url: str) -> dict[str, dict[str, object]]:
    """Tables, their columns and their indexes, as the database reports them."""
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        shape: dict[str, dict[str, object]] = {}
        for table in sorted(insp.get_table_names()):
            if table == "alembic_version":
                continue  # bookkeeping, present only on the migrated side
            columns = {
                c["name"]: (type(c["type"]).__name__, bool(c["nullable"]))
                for c in insp.get_columns(table)
            }
            indexes = {i["name"]: tuple(i["column_names"]) for i in insp.get_indexes(table)}
            shape[table] = {"columns": columns, "indexes": indexes}
        return shape
    finally:
        engine.dispose()


def test_migrations_apply_cleanly_to_an_empty_database(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'migrated.sqlite').as_posix()}"
    command.upgrade(_alembic_config(url), "head")

    tables = set(_shape(url))
    expected = set(Base.metadata.tables)
    assert tables == expected, f"migrated store has {tables}, models declare {expected}"


def test_a_migrated_store_and_a_created_store_have_the_same_schema(tmp_path: Path) -> None:
    """The point of the exercise. Two ways to build one store must agree.

    Without this, a column added to a model and not to a migration passes every
    other test in the suite - because every other test builds its store with
    ``create_all`` and never sees the migration at all.
    """
    migrated_url = f"sqlite:///{(tmp_path / 'migrated.sqlite').as_posix()}"
    created_url = f"sqlite:///{(tmp_path / 'created.sqlite').as_posix()}"

    command.upgrade(_alembic_config(migrated_url), "head")

    engine = create_engine(created_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    migrated, created = _shape(migrated_url), _shape(created_url)
    assert migrated.keys() == created.keys()
    for table in created:
        assert migrated[table]["columns"] == created[table]["columns"], (
            f"{table}: migration and model disagree on columns - "
            f"run `alembic revision --autogenerate`"
        )
        assert migrated[table]["indexes"] == created[table]["indexes"], (
            f"{table}: migration and model disagree on indexes"
        )


def test_the_migration_can_be_rolled_back(tmp_path: Path) -> None:
    """A migration that cannot be undone is a one-way door, not a migration."""
    url = f"sqlite:///{(tmp_path / 'roundtrip.sqlite').as_posix()}"
    cfg = _alembic_config(url)

    command.upgrade(cfg, "head")
    assert _shape(url), "nothing was created"

    command.downgrade(cfg, "base")
    assert _shape(url) == {}, "downgrade left tables behind"


def test_autogenerate_finds_nothing_left_to_do(tmp_path: Path) -> None:
    """The migrations are current with the models.

    Catches the real failure mode: a model gains a column, every suite passes
    because they all use ``create_all``, and the migration silently falls behind.
    """
    pytest.importorskip("alembic.autogenerate")
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    url = f"sqlite:///{(tmp_path / 'current.sqlite').as_posix()}"
    command.upgrade(_alembic_config(url), "head")

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "render_as_batch": True}
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], f"the models have moved ahead of the migrations: {diff}"
