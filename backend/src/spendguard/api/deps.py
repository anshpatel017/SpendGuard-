"""What a request needs: the case store, a read-only DuckDB connection, and where reports live.

The paths are fixed when the app is built (``create_app``), not read from global
settings per request, so one process can serve the operational stores or an
evaluation seed's stores without the two ever mixing.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import duckdb
from fastapi import Depends, HTTPException, Request
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class AppStores:
    duckdb_path: Path
    engine: Engine
    eval_dir: Path
    demo_source: Path  # clean data the live demo copies from - never the data being served


def stores(request: Request) -> AppStores:
    found: AppStores = request.app.state.stores
    return found


def duck(store: Annotated[AppStores, Depends(stores)]) -> Iterator[duckdb.DuckDBPyConnection]:
    """A read-only connection per request (API-CONTRACT: DuckDB opened read-only, always)."""
    if not store.duckdb_path.exists():
        raise HTTPException(
            503,
            detail={
                "code": "dataset_not_initialized",
                "message": (
                    f"Dataset is not initialized ({store.duckdb_path.name} not found). "
                    "Run the ingestion pipeline with `spendguard ingest <path-to-csv>` before requesting cases."
                ),
            },
        )

    try:
        con = duckdb.connect(str(store.duckdb_path), read_only=True)
    except duckdb.Error as exc:
        msg = str(exc).lower()
        if "lock" in msg or "conflict" in msg or "resource temporarily unavailable" in msg:
            raise HTTPException(
                503,
                detail={
                    "code": "database_locked",
                    "message": (
                        "DuckDB database is currently locked by an active process (such as ingestion or detection). "
                        "Wait for the background pipeline write to complete before requesting data."
                    ),
                },
            ) from exc
        raise HTTPException(
            503,
            detail={
                "code": "duckdb_unavailable",
                "message": f"Cannot open {store.duckdb_path.name}: {exc}. Run `spendguard ingest`.",
            },
        ) from exc
    try:
        yield con
    finally:
        con.close()


Stores = Annotated[AppStores, Depends(stores)]
Duck = Annotated[duckdb.DuckDBPyConnection, Depends(duck)]


def not_found(what: str, key: object) -> HTTPException:
    return HTTPException(404, detail={"code": "not_found", "message": f"No {what} {key}."})
