"""The frozen demo state - ``spendguard freeze`` and ``spendguard serve --frozen`` (Phase 9).

    freeze   copy an evaluation run's database, case store and reports into
             data/frozen/demo/, with a manifest of SHA-256 hashes
    serve    check the hashes, copy the snapshot to a working folder, serve the copy

Why a snapshot at all: audit notes come from a language model, so running the
pipeline again does not reproduce them word for word. The demonstration has to
show the notes that were checked, not whatever a rerun happens to produce.

Why serve a copy: a presenter who confirms or dismisses a case during a demo
writes to the case store. Serving a fresh copy of the snapshot each time means
every demonstration starts from exactly the same state, and the snapshot itself
is never modified - which the manifest lets anyone check.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spendguard.config import settings

MANIFEST = "manifest.json"
DUCKDB_NAME = "spendguard.duckdb"


class FrozenStateError(RuntimeError):
    """The snapshot is missing, incomplete, or has changed since it was frozen."""


@dataclass(frozen=True)
class FrozenPaths:
    duckdb_path: Path
    database_url: str
    eval_dir: Path
    manifest: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _latest(directory: Path, pattern: str) -> Path | None:
    found = sorted(directory.glob(pattern))
    return found[-1] if found else None


def freeze(
    seed: int,
    *,
    injected_db: Path,
    eval_dir: Path,
    out_dir: Path | None = None,
    commit: str | None = None,
) -> dict[str, Any]:
    """Snapshot one evaluation run. Replaces any previous snapshot in ``out_dir``."""
    out_dir = out_dir or settings.frozen_data_dir / "demo"
    store = eval_dir / f"investigation_seed{seed}.sqlite"
    missing = [p for p in (injected_db, store) if not p.exists()]
    if missing:
        raise FrozenStateError(f"Nothing to freeze: {', '.join(map(str, missing))} not found.")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "eval").mkdir(parents=True)
    files = {DUCKDB_NAME: injected_db, f"eval/{store.name}": store}
    for pattern in (f"eval-*-seed{seed}.json", f"investigate-eval-*-seed{seed}.json"):
        report = _latest(eval_dir, pattern)
        if report is not None:
            files[f"eval/{report.name}"] = report
    for relative, source in files.items():
        shutil.copy2(source, out_dir / relative)

    manifest = {
        "seed": seed,
        "frozen_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "commit": commit,
        "files": {rel: _sha256(out_dir / rel) for rel in sorted(files)},
    }
    (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify(frozen_dir: Path) -> dict[str, Any]:
    """The manifest, if every file is present and unchanged; otherwise refuse."""
    manifest_path = frozen_dir / MANIFEST
    if not manifest_path.exists():
        raise FrozenStateError(f"No frozen demo at {frozen_dir}. Run `spendguard freeze` first.")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed = [
        rel
        for rel, expected in manifest["files"].items()
        if not (frozen_dir / rel).exists() or _sha256(frozen_dir / rel) != expected
    ]
    if changed:
        raise FrozenStateError(
            f"The frozen demo has changed since it was frozen: {', '.join(changed)}. "
            "Freeze it again, or restore it."
        )
    return manifest


def prepare(frozen_dir: Path | None = None, work_dir: Path | None = None) -> FrozenPaths:
    """Verify the snapshot and lay out a fresh working copy to serve."""
    frozen_dir = frozen_dir or settings.frozen_data_dir / "demo"
    work_dir = work_dir or frozen_dir.with_name(frozen_dir.name + "-live")
    manifest = verify(frozen_dir)
    try:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        shutil.copytree(frozen_dir, work_dir)
    except OSError as exc:  # on Windows, a file another process has open cannot be replaced
        raise FrozenStateError(
            f"Cannot reset the working copy at {work_dir}: {exc.strerror}. Is another "
            "`spendguard serve --frozen` still running? Stop it and try again."
        ) from exc
    store = work_dir / "eval" / f"investigation_seed{manifest['seed']}.sqlite"
    return FrozenPaths(
        duckdb_path=work_dir / DUCKDB_NAME,
        database_url=f"sqlite:///{store.as_posix()}",
        eval_dir=work_dir / "eval",
        manifest=manifest,
    )
