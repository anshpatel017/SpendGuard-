"""The live injection demonstration (FR-5.10) - the one request that runs detectors.

The single exception to "the API never runs a detector inside a request"
(D-10), allowed because it is bounded - a few months of data, a capped number
of anomalies, a few seconds - and because it only ever writes to a temporary
copy that is deleted before the response is sent (see spendguard.demo).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException

from spendguard.api.deps import Stores
from spendguard.api.schemas import DemoInjectRequest, DemoInjectResponse, DemoInjectResult
from spendguard.demo import DemoBusyError, live_injection_demo

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post(
    "/inject",
    response_model=DemoInjectResponse,
    responses={409: {"description": "A demo is already running, or no clean data to copy"}},
)
def inject_demo(body: DemoInjectRequest, store: Stores) -> DemoInjectResponse:
    """Plant anomalies in a bounded copy of the clean data, detect, report what was caught."""
    try:
        run = live_injection_demo(body.anomaly_count, body.seed, source_db=store.demo_source)
    except DemoBusyError as exc:
        raise HTTPException(409, detail={"code": "demo_busy", "message": str(exc)}) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, detail={"code": "demo_unavailable", "message": str(exc)}) from exc
    return DemoInjectResponse(
        seed=run.seed,
        dataset_rows=run.dataset_rows,
        window_start=run.window_start,
        window_end=run.window_end,
        requested=run.requested,
        caught=run.caught,
        other_cases=run.other_cases,
        results=[
            DemoInjectResult(
                injection_group_id=r.injection_group_id,
                anomaly_type=r.anomaly_type,  # type: ignore[arg-type]
                injected_row_ids=r.injected_row_ids,
                amount_at_risk=Decimal(f"{r.amount_at_risk:.2f}"),
                detected=r.detected,
                detected_by=r.detected_by,
                case_id=UUID(r.case_id) if r.case_id else None,
                detector_score=r.detector_score,
            )
            for r in run.results
        ],
        elapsed_seconds=run.elapsed_seconds,
    )
