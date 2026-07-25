import datetime as dt

import pytest
from fastapi import HTTPException, status
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from mainframe.endpoints.performance import public_statistics, rule_performance
from mainframe.models.orm import Rule, Scan, Status
from mainframe.performance_monitor import PerformanceMonitor, read_performance_status


def replace_performance_data(session: Session) -> None:
    rule = Rule(name="metrics-rule")
    with session.begin():
        session.execute(
            update(Scan).values(
                status=Status.FAILED,
                score=None,
                reported_at=None,
            )
        )
        session.add_all(
            [
                Scan(
                    name="metrics-safe",
                    version="1",
                    status=Status.FINISHED,
                    score=7,
                    queued_by="test",
                    rules=[rule],
                ),
                Scan(
                    name="metrics-production",
                    version="1",
                    status=Status.FINISHED,
                    score=8,
                    queued_by="test",
                    reported_at=dt.datetime(2026, 7, 25, tzinfo=dt.UTC),
                    rules=[rule],
                ),
                Scan(
                    name="metrics-failed",
                    version="1",
                    status=Status.FAILED,
                    queued_by="test",
                ),
            ]
        )


def test_read_performance_status_uses_durable_database_state(
    db_session: Session,
) -> None:
    now = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    replace_performance_data(db_session)

    with db_session.begin():
        snapshot = read_performance_status(db_session, now=now)

    assert snapshot.packages_scanned == 2
    assert snapshot.packages_above_production_threshold == 1
    assert snapshot.packages_reported == 1
    assert snapshot.production_score_threshold == 8
    assert snapshot.rule_hits["metrics-rule"] == 2
    assert snapshot.sampled_at == now


def test_performance_monitor_refreshes_from_database(
    db_session: Session,
    engine: Engine,
) -> None:
    now = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    replace_performance_data(db_session)

    snapshot = PerformanceMonitor(engine).refresh(now=now)

    assert snapshot.packages_scanned == 2
    assert snapshot.packages_above_production_threshold == 1
    assert snapshot.packages_reported == 1


def test_rule_performance_endpoint_includes_full_rule_names(
    db_session: Session,
    engine: Engine,
) -> None:
    now = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    replace_performance_data(db_session)
    monitor = PerformanceMonitor(engine)
    monitor.refresh(now=now)

    response = rule_performance(monitor)

    assert response.hits["metrics-rule"] == 2
    assert all(hit_count == 0 for rule_name, hit_count in response.hits.items() if rule_name != "metrics-rule")
    assert response.sampled_at == now


def test_public_statistics_exposes_only_approved_totals(
    db_session: Session,
    engine: Engine,
) -> None:
    now = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    replace_performance_data(db_session)
    monitor = PerformanceMonitor(engine)
    monitor.refresh(now=now)

    response = public_statistics(monitor)

    assert response.model_dump() == {
        "packages_scanned": 2,
        "packages_reported": 1,
        "sampled_at": now,
    }
    assert "rule" not in response.model_dump_json()
    assert "threshold" not in response.model_dump_json()


def test_rule_performance_endpoint_is_unavailable_before_initial_snapshot(
    engine: Engine,
) -> None:
    monitor = PerformanceMonitor(engine)

    with pytest.raises(HTTPException) as error:
        rule_performance(monitor)

    assert error.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_public_statistics_is_unavailable_before_initial_snapshot(
    engine: Engine,
) -> None:
    monitor = PerformanceMonitor(engine)

    with pytest.raises(HTTPException) as error:
        public_statistics(monitor)

    assert error.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
