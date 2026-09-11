"""Shared fixtures. Generated data is session-scoped: built once, reused by every test."""

from __future__ import annotations

from pathlib import Path

import pytest

from spendguard.pipeline.ingest import IngestResult, ingest
from spendguard.pipeline.mapping import DatasetMapping, load_mapping
from spendguard.pipeline.synthetic import GeneratorConfig, SyntheticDataset, generate, write

SMALL = GeneratorConfig(n_transactions=3_000, seed=7)


@pytest.fixture(scope="session")
def small_dataset() -> SyntheticDataset:
    return generate(SMALL)


@pytest.fixture(scope="session")
def small_csv(tmp_path_factory: pytest.TempPathFactory, small_dataset: SyntheticDataset) -> Path:
    csv_path, _ = write(small_dataset, tmp_path_factory.mktemp("raw") / "small.csv")
    return csv_path


@pytest.fixture(scope="session")
def synthetic_mapping() -> DatasetMapping:
    return load_mapping("synthetic_inr")


@pytest.fixture(scope="session")
def ingested(
    tmp_path_factory: pytest.TempPathFactory, small_csv: Path, synthetic_mapping: DatasetMapping
) -> IngestResult:
    out = tmp_path_factory.mktemp("db")
    return ingest(small_csv, synthetic_mapping, db_path=out / "t.duckdb", card_dir=out)
