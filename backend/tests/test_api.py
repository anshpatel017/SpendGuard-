"""The HTTP API (docs/API-CONTRACT.md): what it serves, what it refuses, what it never leaks.

Built on a small hand-made dataset with planted rows, so the answer-key test has
something to leak, and a case store holding one verified note, one agent
dismissal and a queue of uninvestigated cases.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from spendguard.agent.checks import check_citations
from spendguard.agent.investigator import InvestigationResult, TraceStep
from spendguard.agent.note import InvestigatorNote
from spendguard.api import create_app
from spendguard.cases import AnomalyType, Case
from spendguard.db.store import (
    CaseStatus,
    get_engine,
    record_run,
    save_cases,
    save_investigation,
    set_status,
)

from .conftest import build_db

DAY0 = date(2025, 4, 1)
API = "/api/v1"


def _case(rows: list[int], kind: str, amount: float, score: float = 0.9) -> Case:
    return Case.build(
        detector={"duplicate": "d1", "split": "d2", "inflation": "d3"}[kind],
        anomaly_type=AnomalyType(kind), row_ids=rows, detector_score=score,
        amount_at_risk=amount, vendor_key="sharma traders", metadata={"why": kind},
    )  # fmt: skip


DUPLICATE = _case([1, 2], "duplicate", 87_450.0, 0.99)
SPLIT = _case([3, 4, 5], "split", 3_60_000.0)
INFLATION = _case([6], "inflation", 9_000.0, 0.7)
QUEUED = [_case([10 + i], "inflation", 1_000.0 * (i + 1), 0.6) for i in range(5)]

NOTE = {
    "verdict": "likely_true_positive",
    "finding": "Rows 1 and 2 record the same obligation twice, six days apart.",
    "claims": [
        {
            "text": "Both records are for Rs 87,450.",
            "row_ids": [1, 2],
            "facts": [{"row_id": 1, "field": "amount", "value": 87450.0}],
        },
        {"text": "A nearby order from the same supplier differs.", "row_ids": [20]},
    ],
    "policy_clauses": ["SG-PP-4.4"],
    "recommended_action": "Hold any payment against row 2 and confirm with the supplier.",
}


def _result(case: Case, note: dict[str, Any], con: Any, status: str) -> InvestigationResult:
    parsed = InvestigatorNote.model_validate(note)
    report = check_citations(con, parsed, {"SG-PP-4.4"})
    report.semantic_ran = True
    for c in report.citations:
        c.supports_claim = True
    return InvestigationResult(
        case_id=case.case_id,
        anomaly_type=case.anomaly_type.value,
        status="completed",
        model="scripted",
        note=parsed,
        severity_final=case.severity_prelim if note["verdict"] != "likely_false_positive" else 20.0,
        severity_band="high" if note["verdict"] != "likely_false_positive" else "low",
        trace=[
            TraceStep(
                0, "model", prompt_tokens=900, completion_tokens=40, note="requested calculator"
            ),
            TraceStep(
                1,
                "tool",
                tool_name="calculator",
                tool_args={"expression": "87450*2"},
                tool_result={"result": 174900.0},
                latency_ms=2,
            ),
            TraceStep(
                2, "model", prompt_tokens=1200, completion_tokens=300, note="replied with a note"
            ),
            TraceStep(3, "check", role="verifier", note="3/3 citations exist and match"),
            TraceStep(4, "judge", role="verifier", prompt_tokens=700, note="2/2 claims supported"),
        ],
        verification=report,
        first_check=report,
        verification_status=status,
    )


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Any]:
    rows: list[dict[str, object]] = [
        {"amount": 87450.0, "txn_date": DAY0, "invoice_no": "INV-04471"},
        {"amount": 87450.0, "txn_date": DAY0 + timedelta(days=6), "invoice_no": "4471/2025",
         "is_injected": True, "injection_group_id": "g-dup-1", "injection_type": "duplicate",
         "source_row_ref": None},
    ]  # fmt: skip
    rows += [
        {"amount": 1_000.0 + i, "txn_date": DAY0 + timedelta(days=i), "source_row_ref": f"L{i}"}
        for i in range(30)
    ]
    con = build_db(tmp_path / "t.duckdb", rows)
    url = f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}"
    engine = get_engine(url)
    save_cases(engine, "detect-1", "test", [DUPLICATE, SPLIT, INFLATION, *QUEUED])
    save_investigation(engine, "inv-1", _result(DUPLICATE, NOTE, con, "verified"))
    dismissal = {**NOTE, "verdict": "likely_false_positive", "claims": [NOTE["claims"][0]]}
    save_investigation(engine, "inv-1", _result(INFLATION, dismissal, con, "failed_after_retries"))
    record_run(engine, "detect-1", "detect", "test", {}, {"cases": 8}, started_at=_now())
    con.close()
    return {"duckdb_path": tmp_path / "t.duckdb", "database_url": url, "tmp": tmp_path}


def _now() -> Any:
    from datetime import datetime

    return datetime(2026, 9, 21, 10, 0)


@pytest.fixture
def client(paths: dict[str, Any]) -> TestClient:
    app = create_app(
        duckdb_path=paths["duckdb_path"],
        database_url=paths["database_url"],
        eval_dir=paths["tmp"] / "eval",
        frontend_dist=paths["tmp"] / "no-build",
    )
    return TestClient(app)


def ids(response: Any) -> list[str]:
    return [item["case_id"] for item in response.json()["items"]]


# ------------------------------------------------------------------ the queue


def test_the_queue_is_highest_severity_first_with_its_note_summary(client: TestClient) -> None:
    body = client.get(f"{API}/cases").json()
    assert body["total"] == 8 and body["currency"] == "INR"
    severities = [i["severity_prelim"] for i in body["items"]]
    assert severities == sorted(severities, reverse=True)
    top = next(i for i in body["items"] if i["case_id"] == DUPLICATE.case_id)
    assert top["verdict"] == "likely_true_positive"
    assert top["verification_status"] == "verified"
    assert (top["citations_passed"], top["citations_checked"]) == (3, 3)
    assert top["finding_excerpt"].startswith("Rows 1 and 2")
    queued = next(i for i in body["items"] if i["case_id"] == SPLIT.case_id)
    assert queued["verdict"] is None and queued["verification_status"] is None  # explicit nulls


def test_money_leaves_as_a_string(client: TestClient) -> None:
    item = next(
        i for i in client.get(f"{API}/cases").json()["items"] if i["anomaly_type"] == "split"
    )
    assert item["amount_at_risk"] == "360000.00"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"anomaly_type": "split"}, {SPLIT.case_id}),
        ({"anomaly_type": ["split", "duplicate"]}, {SPLIT.case_id, DUPLICATE.case_id}),
        ({"investigated": "true"}, {DUPLICATE.case_id, INFLATION.case_id}),
        ({"verdict": "likely_false_positive"}, {INFLATION.case_id}),
        ({"dismissed_by_agent": "true"}, {INFLATION.case_id}),
        ({"verification_status": "verified"}, {DUPLICATE.case_id}),
        ({"min_amount": "50000"}, {DUPLICATE.case_id, SPLIT.case_id}),
    ],
)
def test_the_queue_filters(client: TestClient, params: dict[str, Any], expected: set[str]) -> None:
    assert set(ids(client.get(f"{API}/cases", params=params))) == expected


def test_the_queue_pages_and_caps_the_page_size(client: TestClient) -> None:
    first = client.get(f"{API}/cases", params={"page_size": 3, "sort": "amount_at_risk"}).json()
    second = client.get(
        f"{API}/cases", params={"page_size": 3, "page": 2, "sort": "amount_at_risk"}
    ).json()
    assert first["total"] == second["total"] == 8
    assert not set(ids_of(first)) & set(ids_of(second))
    assert client.get(f"{API}/cases", params={"page_size": 10_000}).json()["page_size"] == 200


def ids_of(body: dict[str, Any]) -> list[str]:
    return [i["case_id"] for i in body["items"]]


def test_severity_final_sorts_uninvestigated_cases_last_either_way(client: TestClient) -> None:
    for order in ("asc", "desc"):
        items = client.get(
            f"{API}/cases", params={"sort": "severity_final", "order": order}
        ).json()["items"]
        finals = [i["severity_final"] for i in items]
        assert finals[:2] != [None, None] and finals[-1] is None


def test_an_unknown_filter_value_is_a_structured_422(client: TestClient) -> None:
    response = client.get(f"{API}/cases", params={"status": "closed"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"


# ------------------------------------------------------------------ one case


def test_the_case_detail_has_the_note_its_checks_evidence_and_trace(client: TestClient) -> None:
    body = client.get(f"{API}/cases/{DUPLICATE.case_id}").json()
    note = body["audit_note"]
    assert note["verification_status"] == "verified"
    assert [(c["claim_index"], c["row_id"]) for c in note["citations"]] == [(0, 1), (0, 2), (1, 20)]
    first = note["citations"][0]
    assert first["asserted"] == {"amount": 87450.0}
    assert first["row_exists"] and first["values_match"] and first["supports_claim"]

    assert [r["row_id"] for r in body["evidence_rows"]] == [1, 2]
    assert all(r["in_case"] and r["cited"] for r in body["evidence_rows"])
    context = body["context_rows"]
    assert context[0]["row_id"] == 20 and context[0]["cited"]  # cited outside the case: first
    assert not any(r["in_case"] for r in context)
    assert len(context) <= 1 + 15

    assert [s["role"] for s in body["trace"]] == ["investigator"] * 3 + ["verifier"] * 2
    assert body["trace"][1]["tool_result"] == {"result": 174900.0}
    assert body["case"]["metadata"] == {"why": "duplicate"}


def test_an_uninvestigated_case_has_no_note_rather_than_a_note_of_nulls(client: TestClient) -> None:
    body = client.get(f"{API}/cases/{SPLIT.case_id}").json()
    assert body["audit_note"] is None and body["trace"] == []
    assert body["evidence_total"] == 3 and len(body["evidence_rows"]) == 3


def test_an_unknown_case_is_a_structured_404(client: TestClient) -> None:
    response = client.get(f"{API}/cases/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "not_found",
        "message": "No case 00000000-0000-0000-0000-000000000000.",
    }


def test_evidence_pages_through_a_large_case(client: TestClient) -> None:
    body = client.get(f"{API}/cases/{SPLIT.case_id}/evidence", params={"limit": 2}).json()
    rest = client.get(f"{API}/cases/{SPLIT.case_id}/evidence", params={"offset": 2}).json()
    assert body["total"] == 3
    assert [r["row_id"] for r in body["rows"] + rest["rows"]] == [3, 4, 5]


def test_the_answer_key_never_leaves_the_api(client: TestClient) -> None:
    """Row 2 is planted. Nothing served may say so, or hint at it."""
    served = "".join(
        client.get(path).text
        for path in (
            f"{API}/cases/{DUPLICATE.case_id}",
            f"{API}/cases/{DUPLICATE.case_id}/evidence",
            f"{API}/transactions/2",
            f"{API}/cases",
        )
    )
    for hidden in ("is_injected", "injection_group_id", "injection_type", "g-dup-1",
                   "source_row_ref", "source_dataset"):  # fmt: skip
        assert hidden not in served


def test_a_single_transaction_can_be_inspected(client: TestClient) -> None:
    row = client.get(f"{API}/transactions/1").json()
    assert (row["invoice_no"], row["amount"], row["txn_date"]) == (
        "INV-04471",
        "87450.00",
        "2025-04-01",
    )
    assert client.get(f"{API}/transactions/999999").status_code == 404


# ------------------------------------------------------------------ the review action


def test_a_reviewer_confirms_a_case_with_a_note(client: TestClient) -> None:
    response = client.patch(
        f"{API}/cases/{DUPLICATE.case_id}/status",
        json={"status": "confirmed", "reviewer_note": "Recovery initiated."},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    assert response.json()["reviewer_note"] == "Recovery initiated."
    assert client.get(f"{API}/cases/{DUPLICATE.case_id}").json()["case"]["status"] == "confirmed"


def test_a_reviewer_can_clear_a_note_and_it_becomes_null(client: TestClient) -> None:
    url = f"{API}/cases/{SPLIT.case_id}/status"
    client.patch(url, json={"status": "under_review", "reviewer_note": "Asked the officer."})
    kept = client.patch(url, json={"status": "confirmed"}).json()  # no note: unchanged
    assert kept["reviewer_note"] == "Asked the officer."
    cleared = client.patch(url, json={"status": "confirmed", "reviewer_note": "  "}).json()
    assert cleared["reviewer_note"] is None  # null, never an empty string


def test_a_case_dismissed_by_the_agent_stays_findable_after_review(client: TestClient) -> None:
    """FR-5.4: the agent's recommendation is not erased by a person's decision."""
    client.patch(f"{API}/cases/{INFLATION.case_id}/status", json={"status": "under_review"})
    assert ids(client.get(f"{API}/cases", params={"dismissed_by_agent": "true"})) == [
        INFLATION.case_id
    ]


def test_the_review_action_refuses_bad_input(client: TestClient) -> None:
    bad = client.patch(f"{API}/cases/{SPLIT.case_id}/status", json={"status": "closed"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "validation_error"
    missing = client.patch(
        f"{API}/cases/00000000-0000-0000-0000-000000000000/status", json={"status": "confirmed"}
    )
    assert missing.status_code == 404


# ------------------------------------------------------------------ metrics, runs, health


def test_metrics_add_up_and_follow_review_decisions(
    client: TestClient, paths: dict[str, Any]
) -> None:
    before = client.get(f"{API}/metrics").json()
    assert before["cases_flagged"] == before["cases_investigated"] + before["cases_queued"] == 8
    assert before["cases_investigated"] == 2
    assert before["total_transactions"] == 32
    assert before["by_verification_status"] == {"verified": 1, "failed_after_retries": 1}
    assert before["by_anomaly_type"]["inflation"]["count"] == 6
    assert before["money_at_risk_confirmed"] == "0.00"

    engine = get_engine(paths["database_url"])
    set_status(engine, DUPLICATE.case_id, CaseStatus.CONFIRMED)
    set_status(engine, SPLIT.case_id, CaseStatus.DISMISSED)
    after = client.get(f"{API}/metrics").json()
    assert after["money_at_risk_confirmed"] == "87450.00"
    dropped = float(before["money_at_risk"]) - float(after["money_at_risk"])
    assert dropped == pytest.approx(360_000.0)  # a dismissed case is no longer at risk
    assert after["last_run_id"] == "detect-1"


def test_runs_are_listed_newest_first(client: TestClient) -> None:
    runs = client.get(f"{API}/runs").json()
    assert runs[0]["run_id"] == "detect-1" and runs[0]["kind"] == "detect"


def test_health_reports_without_calling_the_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dashboard polls health; probing the LLM would spend the day's quota."""

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("health must not call the LLM")

    monkeypatch.setattr("openai.OpenAI", forbidden, raising=False)
    body = client.get(f"{API}/health").json()
    assert body["status"] == "ok" and body["duckdb"] and body["case_store"]


def test_a_missing_database_degrades_health_and_is_a_structured_503(paths: dict[str, Any]) -> None:
    app = create_app(duckdb_path=paths["tmp"] / "absent.duckdb", database_url=paths["database_url"])
    client = TestClient(app)
    assert client.get(f"{API}/health").json()["status"] == "degraded"
    response = client.get(f"{API}/metrics")
    assert response.status_code == 503 and response.json()["detail"]["code"] == "duckdb_unavailable"


# ------------------------------------------------------------------ evaluation


def test_evaluation_reports_what_was_measured_and_nulls_what_was_not(
    client: TestClient, paths: dict[str, Any]
) -> None:
    empty = client.get(f"{API}/evaluation", params={"seed": 42}).json()
    assert empty["detector_metrics"] == [] and empty["agent_metrics"]["notes"] == 0
    assert empty["agent_metrics"]["citation_validity_deterministic"] is None  # not 0

    eval_dir = paths["tmp"] / "eval"
    eval_dir.mkdir()
    metric = {"anomaly_type": "duplicate", "granularity": "case", "precision": 1.0, "recall": 0.9,
              "f1": 0.947, "pr_auc": 0.9, "tp": 9, "fp": 0, "fn": 1}  # fmt: skip
    (eval_dir / "eval-20260101T000000-seed42.json").write_text(
        json.dumps(
            {
                "run_id": "eval-20260101T000000-seed42",
                "db_path": "x/injected_seed42.duckdb",
                "ground_truth_groups": {"duplicate": 10},
                "metrics": [
                    {**metric, "detector": "d1"},
                    {
                        **metric,
                        "detector": "d1",
                        "anomaly_type": "split",
                        "f1": 0.0,
                    },  # not D1's type
                    {**metric, "detector": "baseline", "f1": 0.3},
                ],
            }
        ),  # fmt: skip
        encoding="utf-8",
    )
    (eval_dir / "investigation_seed42.sqlite").write_bytes(
        Path(paths["database_url"].removeprefix("sqlite:///")).read_bytes()
    )
    body = client.get(f"{API}/evaluation", params={"seed": 42}).json()
    # D1 never emits split cases, so its meaningless 0.000 there is not served.
    assert [(m["detector"], m["anomaly_type"]) for m in body["detector_metrics"]] == [
        ("d1", "duplicate")
    ]
    assert [m["f1"] for m in body["baseline_metrics"]] == [0.3]
    assert body["injected_anomaly_count"] == 10
    agent = body["agent_metrics"]
    assert agent["notes"] == 2
    assert agent["citation_validity_deterministic"] == pytest.approx(4 / 4)
    assert agent["notes_failed_after_retries"] == 1
    assert agent["avg_tool_calls"] == 1.0


def test_an_ablation_arm_is_reported_beside_the_main_run_never_inside_it(
    client: TestClient, paths: dict[str, Any]
) -> None:
    """The arms answer "what is the agent worth", so they must never move its numbers."""
    eval_dir = paths["tmp"] / "eval"
    eval_dir.mkdir(exist_ok=True)
    store = eval_dir / "investigation_seed42.sqlite"
    store.write_bytes(Path(paths["database_url"].removeprefix("sqlite:///")).read_bytes())

    con = build_db(paths["tmp"] / "arm.duckdb", [{"amount": 87450.0, "txn_date": DAY0}] * 2)
    engine = get_engine(f"sqlite:///{store.as_posix()}")
    arm = _result(SPLIT, NOTE, con, "unverified")
    arm.model = "template"
    save_investigation(engine, "investigate-eval-1-seed42-template", arm, ablation_name="template")
    record_run(
        engine, "investigate-eval-1-seed42-template", "investigate", "injected_seed42",
        {"ablation": "template", "verifier_enabled": False, "model": "scripted"},
        {"cases": 1}, started_at=_now(),
    )  # fmt: skip
    con.close()
    (eval_dir / "investigate-eval-20260101T000000-seed42-template.json").write_text(
        json.dumps({"triage": {"all": {"decisive_accuracy": 0.5}}}), encoding="utf-8"
    )

    body = client.get(f"{API}/evaluation", params={"seed": 42}).json()
    assert body["agent_metrics"]["notes"] == 2  # the arm's note is not one of the agent's
    (row,) = body["ablations"]
    assert row["ablation_name"] == "template" and row["triage_accuracy"] == 0.5
    # Read from the run, not assumed here: that run had the Verifier off, so the
    # arm used no model anywhere and the row must not name one.
    assert row["configuration"] == "notes filled from detector output, no model writes them; no model ran at all"  # fmt: skip


# ------------------------------------------------------------------ contract and frontend


def test_the_committed_openapi_schema_matches_the_api() -> None:
    """The frontend's types are generated from frontend/openapi.json. Drift fails here first."""
    committed = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
    assert committed.exists(), "run `spendguard openapi` and commit frontend/openapi.json"
    assert json.loads(committed.read_text(encoding="utf-8")) == create_app().openapi(), (
        "The API changed: run `spendguard openapi`, then `npm run gen:api` in frontend/"
    )


def test_the_built_dashboard_is_served_with_deep_links(paths: dict[str, Any]) -> None:
    dist = paths["tmp"] / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (paths["tmp"] / "secret.txt").write_text("secret", encoding="utf-8")
    client = TestClient(create_app(
        duckdb_path=paths["duckdb_path"], database_url=paths["database_url"], frontend_dist=dist
    ))  # fmt: skip

    assert client.get("/").text == "<div id=root></div>"
    assert client.get(f"/cases/{SPLIT.case_id}").text == "<div id=root></div>"  # SPA route
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert "secret" not in client.get("/..%2Fsecret.txt").text
    unknown = client.get(f"{API}/nothing-here")
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "not_found"
