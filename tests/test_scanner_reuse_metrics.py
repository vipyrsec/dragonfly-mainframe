import datetime as dt
import uuid
from typing import Literal

import pytest
from fastapi import HTTPException
from prometheus_client import REGISTRY
from pydantic import ValidationError
from sqlalchemy.orm import Session

from mainframe.endpoints.opengrep import submit_opengrep_result
from mainframe.endpoints.package import submit_results
from mainframe.json_web_token import AuthenticationData
from mainframe.metrics import record_scanner_reuse
from mainframe.models.orm import OpenGrepScan, Scan, Status
from mainframe.models.schemas import (
    OpenGrepScanResult,
    OpenGrepScanResultFail,
    PackageScanResult,
    PackageScanResultFail,
    ScannerReuseMetrics,
)


def metrics_payload() -> dict[str, str | int]:
    return dict.fromkeys(ScannerReuseMetrics.model_fields, 0) | {
        "mode": "reuse",
        "lookups": 10,
        "candidate_files": 8,
        "reused_files": 7,
        "reused_bytes": 1024,
        "engine_files": 3,
        "engine_bytes": 100,
        "engine_us": 2000000,
        "overhead_us": 1000,
        "validated_files": 1,
    }


@pytest.mark.parametrize("scanner", ["yara", "opengrep"])
@pytest.mark.parametrize("failed", [False, True])
def test_only_accepted_leases_count_once(
    db_session: Session, auth: AuthenticationData, scanner: Literal["yara", "opengrep"], *, failed: bool
) -> None:
    assignment = uuid.uuid4()
    with db_session.begin():
        scan = Scan(
            name="reuse-metrics",
            version="1",
            queued_by="test",
            status=Status.PENDING,
            pending_by=auth.subject,
            attempt_count=1,
            assignment_id=assignment,
        )
        db_session.add(scan)
        db_session.flush()
        if scanner == "opengrep":
            db_session.add(
                OpenGrepScan(
                    scan_id=scan.scan_id,
                    queued_by="test",
                    queued_at=dt.datetime.now(dt.UTC),
                    status=Status.PENDING,
                    pending_by=auth.subject,
                    attempt_count=1,
                    assignment_id=assignment,
                )
            )
    payload = {
        "name": "reuse-metrics",
        "version": "1",
        "commit": "rules",
        "duration_ms": 2,
        "findings": [],
        "reason": "scan failed",
        "attempt": 1,
        "assignment_id": assignment,
        "scan_reuse": metrics_payload(),
    }
    labels = {"scanner": scanner, "mode": "reuse"}
    before = REGISTRY.get_sample_value("scanner_reuse_reused_files_total", labels)
    assert before is not None
    if scanner == "yara":
        result = PackageScanResultFail.model_validate(payload) if failed else PackageScanResult.model_validate(payload)
        submit_results(result, db_session, auth)
        if failed:
            submit_results(result, db_session, auth)
        else:
            with pytest.raises(HTTPException):
                submit_results(result, db_session, auth)
    else:
        shadow = (
            OpenGrepScanResultFail.model_validate(payload) if failed else OpenGrepScanResult.model_validate(payload)
        )
        submit_opengrep_result(shadow, db_session, auth)
        with pytest.raises(HTTPException):
            submit_opengrep_result(shadow, db_session, auth)
    assert REGISTRY.get_sample_value("scanner_reuse_reused_files_total", labels) == before + 7
    timestamp = REGISTRY.get_sample_value("scanner_reuse_last_report_timestamp_seconds", labels)
    assert timestamp is not None
    assert timestamp > 0


@pytest.mark.parametrize("invalid", [-1, 2**63, True, "1"])
def test_metrics_counts_are_bounded_strict_integers(invalid: object) -> None:
    payload = metrics_payload() | {"reused_files": invalid}
    with pytest.raises(ValidationError):
        ScannerReuseMetrics.model_validate(payload)


def test_old_workers_need_no_telemetry() -> None:
    record_scanner_reuse("yara", None)
    assert PackageScanResult(name="legacy", version="1", commit="old").scan_reuse is None
