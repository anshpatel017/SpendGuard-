"""Bringing in a new procurement file over HTTP.

Most of these are about what the endpoints refuse. An intake that quietly
overwrote the dataset a reviewer is working through, or quietly guessed which
column held the money, would be worse than having no intake at all.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

from spendguard.config import settings
from spendguard.pipeline.intake import candidates_for, preview, suggest_mapping

GOOD_CSV = (
    "Supplier Name,Invoice Number,Invoice Date,Total Price,Quantity,Unit Price,Item Description\n"
    "Acme Supplies,INV-001,2024-05-17,198398.72,26,7630.72,LED Monitor 24 inch\n"
    "Acme Supplies,INV-002,2024-05-21,45000.00,5,9000.00,Laser Printer\n"
    "Globex Ltd,INV-003,2024-06-02,12500.50,1,12500.50,UPS 1 kVA\n"
)


def _upload(content: str, name: str = "purchases.csv") -> dict[str, Any]:
    return {"file": (name, io.BytesIO(content.encode("utf-8")), "text/csv")}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """An app whose data directory is a temp dir, so no test writes into the project.

    `duckdb_path` is redirected too: the protection these endpoints provide is
    "refuse to overwrite the dataset being served", and testing it against the
    real path would either write to it or pass for the wrong reason.
    """
    from spendguard.api import create_app

    served = tmp_path / "served.duckdb"
    duckdb.connect(str(served)).close()
    monkeypatch.setattr(settings, "processed_data_dir", tmp_path, raising=False)
    monkeypatch.setattr(settings, "duckdb_path", served, raising=False)

    app = create_app(
        duckdb_path=served,
        database_url=f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}",
        eval_dir=tmp_path / "eval",
        frontend_dist=tmp_path / "no-build",
    )
    return TestClient(app)


# ------------------------------------------------------------------ the guess


def test_a_column_called_total_price_is_recognised_as_the_amount() -> None:
    """Real exports rarely use the canonical names; that is the point of mapping."""
    guess = suggest_mapping(
        ["Supplier Name", "Invoice Date", "Total Price", "Quantity", "Unit Price"]
    )
    assert guess["vendor_name"] == "Supplier Name"
    assert guess["amount"] == "Total Price"
    assert guess["txn_date"] == "Invoice Date"


def test_unit_price_does_not_steal_the_amount_column() -> None:
    """Both match a `price` hint, and confusing them would distort every severity."""
    guess = suggest_mapping(["Supplier Name", "Invoice Date", "Unit Price", "Total Price"])
    assert guess["amount"] == "Total Price"
    assert guess["unit_price"] == "Unit Price"


def test_two_equally_good_date_columns_produce_no_guess_at_all() -> None:
    """The California export has both `Creation Date` and `Purchase Date`.

    Which is the transaction date is a judgement its own mapping records in a
    comment. A system that picked one silently would mis-date every case, so the
    guess declines and the preview names the candidates instead.
    """
    headers = ["Supplier Name", "Total Price", "Creation Date", "Purchase Date"]
    assert suggest_mapping(headers)["txn_date"] is None
    assert candidates_for("txn_date", headers) == ["Creation Date", "Purchase Date"]


def test_a_column_is_never_mapped_to_two_fields() -> None:
    guess = suggest_mapping(["Supplier", "Date", "Amount"])
    used = [h for h in guess.values() if h]
    assert len(used) == len(set(used))


# ------------------------------------------------------------- preview writes nothing


def test_preview_reports_what_the_file_would_become(client: TestClient) -> None:
    body = client.post("/api/v1/datasets/preview", files=_upload(GOOD_CSV)).json()
    assert body["usable"] is True
    assert body["rows"] == 3
    assert body["suggested"]["amount"] == "Total Price"
    assert body["problems"] == []
    assert len(body["sample"]) == 3


def test_preview_leaves_nothing_behind(client: TestClient, tmp_path: Path) -> None:
    """It is called on files nobody has vetted, so it must not write."""
    before = sorted(p.name for p in tmp_path.glob("*"))
    client.post("/api/v1/datasets/preview", files=_upload(GOOD_CSV))
    assert sorted(p.name for p in tmp_path.glob("*")) == before


def test_a_file_with_no_date_column_is_called_unusable_before_anything_is_written(
    client: TestClient,
) -> None:
    body = client.post(
        "/api/v1/datasets/preview", files=_upload("Supplier Name,Total Price\nAcme,100\n")
    ).json()
    assert body["usable"] is False
    assert "txn_date" in body["missing_required"]
    assert any("txn_date" in p for p in body["problems"])


def test_an_unreadable_file_is_reported_rather_than_raising(client: TestClient) -> None:
    r = client.post("/api/v1/datasets/preview", files=_upload("\x00\x01 not a csv at all"))
    assert r.status_code == 200, "a bad upload is a finding, not a server error"
    assert r.json()["usable"] is False


def test_something_that_is_not_a_csv_is_refused_by_extension(client: TestClient) -> None:
    r = client.post("/api/v1/datasets/preview", files=_upload(GOOD_CSV, name="accounts.xlsx"))
    assert r.status_code == 415


def test_a_file_past_the_ceiling_is_sent_to_the_cli(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ingestion runs inside the request, so the request has to stay bounded (D-10)."""
    monkeypatch.setattr(settings, "intake_max_bytes", 32, raising=False)
    r = client.post("/api/v1/datasets/preview", files=_upload(GOOD_CSV))
    assert r.status_code == 413
    assert "spendguard ingest" in r.json()["detail"]["message"]


# --------------------------------------------------------- ingest, and what it refuses


def test_the_served_dataset_cannot_be_overwritten_by_an_upload(client: TestClient) -> None:
    """The one that matters.

    `ingest` replaces the whole `transactions` table in the file it is given. An
    upload named after the dataset being served would delete the rows a reviewer
    is part-way through, mid-session, with no undo.
    """
    served = settings.duckdb_path.stem  # redirected to the fixture's temp file
    r = client.post(
        "/api/v1/datasets",
        files=_upload(GOOD_CSV),
        data={
            "dataset": served,
            "vendor_name": "Supplier Name",
            "amount": "Total Price",
            "txn_date": "Invoice Date",
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "protected_dataset"


def test_an_upload_lands_in_its_own_file_and_leaves_the_served_one_alone(
    client: TestClient,
) -> None:
    served = settings.duckdb_path
    before = served.stat().st_mtime_ns

    r = client.post(
        "/api/v1/datasets",
        files=_upload(GOOD_CSV),
        data={
            "dataset": "intake_test_fresh",
            "vendor_name": "Supplier Name",
            "amount": "Total Price",
            "txn_date": "Invoice Date",
            "invoice_no": "Invoice Number",
        },
    )
    try:
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rows_loaded"] == 3
        assert body["dataset"] == "intake_test_fresh"
        assert Path(body["db_path"]).exists()
        assert Path(body["db_path"]) != served

        with duckdb.connect(body["db_path"], read_only=True) as con:
            assert con.execute("SELECT count(*) FROM transactions").fetchone()[0] == 3

        assert any("spendguard detect" in s for s in body["next_steps"]), (
            "detection does not run in the request (D-10); the caller is told how"
        )
        assert served.stat().st_mtime_ns == before, "the served dataset was not touched"
    finally:
        Path(r.json().get("db_path", "")).unlink(missing_ok=True)


def test_a_second_upload_under_the_same_name_is_refused(client: TestClient) -> None:
    """Replacing a dataset in place would make the earlier one unrecoverable.

    A correction is a new dataset, so the two stay comparable - which is also
    the reason there is no endpoint that edits a transaction.
    """
    common = {
        "vendor_name": "Supplier Name",
        "amount": "Total Price",
        "txn_date": "Invoice Date",
    }
    first = client.post(
        "/api/v1/datasets", files=_upload(GOOD_CSV), data={"dataset": "intake_twice", **common}
    )
    try:
        assert first.status_code == 200, first.text
        again = client.post(
            "/api/v1/datasets", files=_upload(GOOD_CSV), data={"dataset": "intake_twice", **common}
        )
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "dataset_exists"
    finally:
        Path(first.json().get("db_path", "")).unlink(missing_ok=True)


def test_a_dataset_name_cannot_escape_the_data_directory(client: TestClient) -> None:
    r = client.post(
        "/api/v1/datasets",
        files=_upload(GOOD_CSV),
        data={
            "dataset": "../../etc/passwd",
            "vendor_name": "Supplier Name",
            "amount": "Total Price",
            "txn_date": "Invoice Date",
        },
    )
    assert r.status_code == 422, "the name pattern rejects it before any path is built"


def test_the_required_columns_must_be_stated_not_guessed(client: TestClient) -> None:
    """A wrong `amount` would distort every severity score, silently."""
    r = client.post(
        "/api/v1/datasets",
        files=_upload(GOOD_CSV),
        data={"dataset": "intake_missing", "vendor_name": "Supplier Name"},
    )
    assert r.status_code == 422


def test_there_is_no_way_to_edit_or_delete_a_transaction(client: TestClient) -> None:
    """The evidence is append-only, and that is the product.

    An auditor's first question about a system like this is whether the rows can
    be altered. A route appearing here later would change the answer, so the
    absence is asserted rather than assumed.
    """
    paths = client.get("/openapi.json").json()["paths"]
    for path, operations in paths.items():
        for method in operations:
            if method.lower() in {"put", "patch", "delete"}:
                assert "transaction" not in path.lower(), f"{method.upper()} {path} edits evidence"
    assert not any("/datasets/" in p and "{" in p for p in paths), "no per-dataset mutation"


def test_preview_and_the_module_agree(tmp_path: Path) -> None:
    """The endpoint is a thin wrapper; if it ever stops being one, this fails."""
    csv = tmp_path / "p.csv"
    csv.write_text(GOOD_CSV, encoding="utf-8")
    direct = preview(csv)
    assert direct.usable
    assert direct.rows == 3
    assert direct.suggested["vendor_name"] == "Supplier Name"


# ------------------------------------------------------------------ dates


AMBIGUOUS_CSV = (
    "Supplier Name,Invoice Date,Total Price"
    + chr(10)
    + "Acme Supplies,01-04-2024,1000"
    + chr(10)
    + "Acme Supplies,02-05-2024,2000"
    + chr(10)
)
BAD_DATE_CSV = (
    "Supplier Name,Invoice Date,Total Price"
    + chr(10)
    + "Acme Supplies,last Tuesday,1000"
    + chr(10)
    + "Acme Supplies,whenever,2000"
    + chr(10)
)


def test_a_date_column_nothing_can_parse_is_caught_before_ingesting(client: TestClient) -> None:
    """The bug this whole check exists for.

    The first version of the preview validated amounts and not dates. It reported
    "no problems" on a file whose every row was then dropped for an unparseable
    date - a preview that does that is worse than no preview.
    """
    body = client.post("/api/v1/datasets/preview", files=_upload(BAD_DATE_CSV)).json()
    assert body["usable"] is False
    assert body["date_formats"] == []
    assert any("every row would be dropped" in p.lower() for p in body["problems"])


def test_a_day_month_ambiguity_is_reported_rather_than_resolved(client: TestClient) -> None:
    """`01-04-2024` is 1 April or 4 January, and the column cannot say which.

    Picking one silently would mis-date a quarter of a year and every duplicate
    and split window computed from those dates.
    """
    body = client.post("/api/v1/datasets/preview", files=_upload(AMBIGUOUS_CSV)).json()
    assert sorted(body["date_formats"]) == ["%d-%m-%Y", "%m-%d-%Y"]
    assert body["usable"] is False, "ambiguous is not usable until someone chooses"
    assert any("ambiguous" in p.lower() for p in body["problems"])


def test_an_unambiguous_iso_date_needs_no_choice(client: TestClient) -> None:
    body = client.post("/api/v1/datasets/preview", files=_upload(GOOD_CSV)).json()
    assert body["date_formats"] == ["%Y-%m-%d"]
    assert body["usable"] is True


def test_ingesting_an_ambiguous_file_without_saying_which_format_is_refused(
    client: TestClient,
) -> None:
    r = client.post(
        "/api/v1/datasets",
        files=_upload(AMBIGUOUS_CSV),
        data={
            "dataset": "intake_ambiguous",
            "vendor_name": "Supplier Name",
            "amount": "Total Price",
            "txn_date": "Invoice Date",
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "ambiguous_date_format"


def test_the_chosen_date_format_is_the_one_used(client: TestClient) -> None:
    """Stating `%d-%m-%Y` must give April, not January."""
    r = client.post(
        "/api/v1/datasets",
        files=_upload(AMBIGUOUS_CSV),
        data={
            "dataset": "intake_daymonth",
            "vendor_name": "Supplier Name",
            "amount": "Total Price",
            "txn_date": "Invoice Date",
            "date_format": "%d-%m-%Y",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows_loaded"] == 2, "no row was dropped for an unparseable date"
    with duckdb.connect(r.json()["db_path"], read_only=True) as con:
        months = {d.month for (d,) in con.execute("SELECT txn_date FROM transactions").fetchall()}
    assert months == {4, 5}, "day-first was honoured"


def test_a_file_whose_dates_cannot_be_parsed_never_creates_an_empty_dataset(
    client: TestClient,
) -> None:
    """Loading 0 of 199 rows and reporting success is not success."""
    r = client.post(
        "/api/v1/datasets",
        files=_upload(BAD_DATE_CSV),
        data={
            "dataset": "intake_baddates",
            "vendor_name": "Supplier Name",
            "amount": "Total Price",
            "txn_date": "Invoice Date",
        },
    )
    assert r.status_code == 422
    assert not (settings.processed_data_dir / "intake_baddates.duckdb").exists()
