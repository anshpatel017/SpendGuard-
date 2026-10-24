"""Bringing a new procurement file into the system (FR-1.3, FR-5.10's sibling).

Two endpoints, and the difference between them is the whole design:

* **`POST /datasets/preview`** reads an uploaded file and reports what it would
  become - which column is which, how many rows survive, what is missing. It
  writes nothing at all, so it is safe to call on anything.
* **`POST /datasets`** actually ingests, and only ever into a **new** DuckDB file.

That second restriction is not a convenience. `ingest` replaces the whole
`transactions` table in the file it is given, so pointing an upload at the
dataset currently being served would delete the rows a reviewer is working
through, mid-session, with no undo. The endpoint refuses by name.

**There is deliberately no endpoint that edits a transaction.** An auditor's
first question about a system like this is whether the evidence can be altered,
and the answer has to be no. A correction is a fresh ingestion of a corrected
source into its own dataset, which leaves the original intact and the two
comparable. What a person *can* change is their own review decision and note,
which is a separate, append-only record (D-04).

Both endpoints respect D-10: no detector and no model runs here. Ingestion is
bounded by `settings.intake_max_bytes` and does file I/O only, which is why it
is allowed where detection is not.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from spendguard.api.schemas import (
    DatasetIngestResponse,
    DatasetPreviewResponse,
)
from spendguard.config import settings
from spendguard.pipeline.ingest import IngestError, ingest
from spendguard.pipeline.intake import (
    dataset_db_path,
    detect_date_formats,
    is_protected,
    mapping_from,
    preview,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])

DATASET_NAME = r"^[a-z0-9_]+$"


def _staged(upload: UploadFile) -> Path:
    """Write the upload to a temp file, refusing anything oversized.

    Streamed in chunks and checked as it goes: reading first and checking after
    would let a large upload exhaust memory before the limit ever applied.
    """
    if not (upload.filename or "").lower().endswith((".csv", ".txt")):
        raise HTTPException(
            415,
            detail={
                "code": "unsupported_file",
                "message": "Upload a CSV file. Export from your finance system as CSV first.",
            },
        )
    tmp = Path(tempfile.mkdtemp(prefix="spendguard-intake-")) / (upload.filename or "upload.csv")
    written = 0
    with tmp.open("wb") as out:
        while chunk := upload.file.read(1 << 20):
            written += len(chunk)
            if written > settings.intake_max_bytes:
                out.close()
                shutil.rmtree(tmp.parent, ignore_errors=True)
                limit = settings.intake_max_bytes // (1 << 20)
                raise HTTPException(
                    413,
                    detail={
                        "code": "file_too_large",
                        "message": f"The file is larger than {limit} MB. "
                        "Ingest it from the command line instead: `spendguard ingest <file>`.",
                    },
                )
            out.write(chunk)
    return tmp


def _date_column(path: Path, column: str) -> list[str]:
    """The date column's values, for deciding its format before ingesting."""
    import polars as pl

    frame = pl.read_csv(path, infer_schema_length=0, truncate_ragged_lines=True, ignore_errors=True)
    if column not in frame.columns:
        raise HTTPException(
            422,
            detail={
                "code": "unknown_column",
                "message": f"The file has no column named `{column}`.",
            },
        )
    return frame[column].cast(pl.Utf8).to_list()


@router.post("/preview", response_model=DatasetPreviewResponse)
def preview_dataset(file: UploadFile = File(...)) -> DatasetPreviewResponse:  # noqa: B008
    """Report what an uploaded file would become. Writes nothing."""
    staged = _staged(file)
    try:
        result = preview(staged)
    finally:
        shutil.rmtree(staged.parent, ignore_errors=True)

    return DatasetPreviewResponse(
        filename=result.filename,
        rows=result.rows,
        headers=result.headers,
        suggested=result.suggested,
        unmapped_headers=result.unmapped_headers,
        missing_required=result.missing_required,
        problems=result.problems,
        date_formats=result.date_formats,
        usable=result.usable,
        sample=[
            {k: None if v is None else str(v) for k, v in row.items()} for row in result.sample
        ],
    )


@router.post(
    "",
    response_model=DatasetIngestResponse,
    responses={
        409: {"description": "That dataset name is taken, or would overwrite served data"},
        413: {"description": "File too large for the API; use the CLI"},
        415: {"description": "Not a CSV"},
        422: {"description": "The file cannot be audited as mapped"},
    },
)
def create_dataset(
    file: UploadFile = File(...),  # noqa: B008
    dataset: str = Form(..., pattern=DATASET_NAME),  # noqa: B008
    vendor_name: str = Form(...),  # noqa: B008
    amount: str = Form(...),  # noqa: B008
    txn_date: str = Form(...),  # noqa: B008
    invoice_no: str | None = Form(None),  # noqa: B008
    officer_id: str | None = Form(None),  # noqa: B008
    item_desc: str | None = Form(None),  # noqa: B008
    item_category: str | None = Form(None),  # noqa: B008
    quantity: str | None = Form(None),  # noqa: B008
    unit_price: str | None = Form(None),  # noqa: B008
    date_format: str | None = Form(None),  # noqa: B008
) -> DatasetIngestResponse:
    """Ingest an uploaded CSV into a new dataset of its own.

    The three required columns are required here too rather than defaulted from
    the guess: a mis-assigned `amount` would silently distort every severity
    score downstream, so the caller states it.
    """
    db_path = dataset_db_path(dataset)
    if is_protected(db_path):
        raise HTTPException(
            409,
            detail={
                "code": "protected_dataset",
                "message": f"`{dataset}` is a dataset this system serves. "
                "Choose another name; ingestion replaces a dataset entirely.",
            },
        )
    if db_path.exists():
        raise HTTPException(
            409,
            detail={
                "code": "dataset_exists",
                "message": f"A dataset named `{dataset}` already exists. "
                "Choose another name, so the earlier one stays comparable.",
            },
        )

    staged = _staged(file)
    try:
        # The date format is settled before ingesting, not left to a default list.
        # `01-04-2024` parses as both 1 April and 4 January, and a default that
        # silently picked one would mis-date every row and every window computed
        # from them. If the caller did not state one, the file has to be
        # unambiguous on its own.
        if date_format is None:
            fits = detect_date_formats(_date_column(staged, txn_date))
            if len(fits) != 1:
                raise HTTPException(
                    422,
                    detail={
                        "code": "ambiguous_date_format",
                        "message": (
                            f"`{txn_date}` matches {len(fits)} date formats "
                            f"({', '.join(fits) or 'none'}). Send `date_format` to say which."
                            if fits
                            else f"No known date format fits `{txn_date}`; every row "
                            "would be dropped."
                        ),
                    },
                )
            date_format = fits[0]

        mapping = mapping_from(
            dataset,
            {
                "vendor_name": vendor_name,
                "amount": amount,
                "txn_date": txn_date,
                "invoice_no": invoice_no,
                "officer_id": officer_id,
                "item_desc": item_desc,
                "item_category": item_category,
                "quantity": quantity,
                "unit_price": unit_price,
            },
            date_formats=[date_format],
        )
        try:
            result = ingest(staged, mapping, db_path=db_path)
        except (IngestError, ValueError) as exc:
            raise HTTPException(422, detail={"code": "ingest_failed", "message": str(exc)}) from exc
    finally:
        shutil.rmtree(staged.parent, ignore_errors=True)

    return DatasetIngestResponse(
        dataset=result.dataset,
        db_path=str(result.db_path),
        source_sha256=result.source_sha256,
        rows_read=result.rows_read,
        rows_loaded=result.rows_loaded,
        rows_dropped=result.rows_dropped,
        dropped=result.dropped,
        duration_seconds=result.duration_seconds,
        # Detection is not run here (D-10). The caller is told exactly how.
        next_steps=[
            f"spendguard detect --db {result.db_path}",
            f"spendguard serve --db {result.db_path}",
        ],
    )
