import datetime as dt
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import HTTPException, status
from sqlalchemy import Engine, delete, event, select, update
from sqlalchemy.orm import Session

from mainframe import performance_projection
from mainframe.endpoints.performance import public_statistics, rule_performance
from mainframe.metrics import rule_hits
from mainframe.models.orm import (
    AlertingConfiguration,
    PerformanceRollup,
    Rule,
    Scan,
    Status,
)
from mainframe.performance_monitor import (
    PerformanceMonitor,
    PerformanceProjectionIncompleteError,
    read_performance_status,
)
from mainframe.performance_projection import PerformanceProjector


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
                Scan(
                    name="metrics-dead-lettered",
                    version="1",
                    status=Status.FAILED,
                    queued_by="test",
                    dead_lettered_at=dt.datetime(2026, 7, 25, tzinfo=dt.UTC),
                ),
            ]
        )


def complete_projection(engine: Engine, *, batch_size: int = 2) -> None:
    projector = PerformanceProjector(engine)
    for _ in range(100):
        batch = projector.process_batch(batch_size=batch_size)
        if batch.initial_backfill_complete and batch.processed == 0:
            return
    pytest.fail("Performance projection did not complete")


def test_projection_processes_history_in_bounded_batches(
    db_session: Session,
    engine: Engine,
) -> None:
    replace_performance_data(db_session)

    batch = PerformanceProjector(engine).process_batch(batch_size=1)

    assert batch.outcomes == 1
    assert batch.reports == 1
    assert batch.initial_backfill_complete is False


def test_projection_is_exactly_once(
    db_session: Session,
    engine: Engine,
) -> None:
    replace_performance_data(db_session)
    complete_projection(engine)
    projector = PerformanceProjector(engine)

    empty_batch = projector.process_batch(batch_size=10)
    with db_session.begin():
        totals = db_session.get(PerformanceRollup, 1)

    assert empty_batch.processed == 0
    assert totals is not None
    assert totals.packages_scanned == 2
    assert totals.packages_reported == 1


@pytest.mark.parametrize(
    ("get_results", "message"),
    [
        ([None], "Performance rollup could not be initialized"),
        ([Mock(), None], "Performance projection state could not be initialized"),
    ],
)
def test_projection_requires_initialized_singletons(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    get_results: list[object | None],
    message: str,
) -> None:
    session = MagicMock()
    session.get.side_effect = get_results
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(performance_projection, "Session", session_factory)

    with pytest.raises(RuntimeError, match=message):
        PerformanceProjector(engine).process_batch(batch_size=1)


def test_projection_rejects_finished_scan_without_score(
    db_session: Session,
    engine: Engine,
) -> None:
    processed_at = dt.datetime(2026, 7, 25, tzinfo=dt.UTC)
    with db_session.begin():
        db_session.execute(update(Scan).values(analytics_outcome_processed_at=processed_at))
        db_session.add(
            Scan(
                name="metrics-scoreless",
                version="1",
                status=Status.FINISHED,
                queued_by="test",
            )
        )

    with pytest.raises(RuntimeError, match=r"Finished scan .* has no score"):
        PerformanceProjector(engine).process_batch(batch_size=1)


def test_projection_picks_up_reports_after_initial_backfill(
    db_session: Session,
    engine: Engine,
) -> None:
    replace_performance_data(db_session)
    complete_projection(engine)
    with db_session.begin():
        scan = db_session.scalar(select(Scan).where(Scan.name == "metrics-safe"))
        assert scan is not None
        scan.reported_at = dt.datetime(2026, 7, 26, tzinfo=dt.UTC)

    batch = PerformanceProjector(engine).process_batch(batch_size=10)
    with db_session.begin():
        totals = db_session.get(PerformanceRollup, 1)

    assert batch.outcomes == 0
    assert batch.reports == 1
    assert totals is not None
    assert totals.packages_reported == 2


def test_projection_picks_up_terminal_scans_after_initial_backfill(
    db_session: Session,
    engine: Engine,
) -> None:
    replace_performance_data(db_session)
    complete_projection(engine)
    with db_session.begin():
        db_session.add(
            Scan(
                name="metrics-later",
                version="1",
                status=Status.FINISHED,
                score=9,
                queued_by="test",
                rules=[Rule(name="later-rule")],
            )
        )

    batch = PerformanceProjector(engine).process_batch(batch_size=10)
    snapshot = PerformanceMonitor(engine).refresh()

    assert batch.outcomes == 1
    assert snapshot.packages_scanned == 3
    assert snapshot.rule_hits["later-rule"] == 1


def test_read_performance_status_uses_compact_rollups(
    db_session: Session,
    engine: Engine,
) -> None:
    now = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    replace_performance_data(db_session)
    complete_projection(engine)
    statements: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        with db_session.begin():
            snapshot = read_performance_status(db_session, now=now)
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert all("FROM scans" not in statement for statement in statements)
    assert all("package_rules" not in statement for statement in statements)
    assert snapshot.packages_scanned == 2
    assert snapshot.packages_failed >= 1
    assert snapshot.packages_dead_lettered == 1
    assert snapshot.packages_above_production_threshold == 1
    assert snapshot.packages_reported == 1
    assert snapshot.production_score_threshold == 8
    assert snapshot.rule_hits["metrics-rule"] == 2
    assert snapshot.sampled_at == now


def test_threshold_changes_only_read_score_rollups(
    db_session: Session,
    engine: Engine,
) -> None:
    replace_performance_data(db_session)
    complete_projection(engine)
    with db_session.begin():
        configuration = db_session.get(AlertingConfiguration, 1)
        assert configuration is not None
        configuration.production_score_threshold = 7

    snapshot = PerformanceMonitor(engine).refresh()

    assert snapshot.packages_above_production_threshold == 2


def test_read_performance_status_waits_for_initial_projection(
    db_session: Session,
) -> None:
    with db_session.begin(), pytest.raises(PerformanceProjectionIncompleteError):
        read_performance_status(db_session, now=dt.datetime.now(dt.UTC))


def test_read_performance_status_requires_alerting_configuration(
    db_session: Session,
    engine: Engine,
) -> None:
    complete_projection(engine)
    with db_session.begin():
        db_session.execute(delete(AlertingConfiguration))

    with db_session.begin(), pytest.raises(RuntimeError, match="Alerting configuration is missing"):
        read_performance_status(db_session, now=dt.datetime.now(dt.UTC))


def test_read_performance_status_requires_rollup(
    db_session: Session,
    engine: Engine,
) -> None:
    complete_projection(engine)
    with db_session.begin():
        db_session.execute(delete(PerformanceRollup))

    with db_session.begin(), pytest.raises(RuntimeError, match="Performance rollup is missing"):
        read_performance_status(db_session, now=dt.datetime.now(dt.UTC))


def test_performance_monitor_refreshes_from_rollups(
    db_session: Session,
    engine: Engine,
) -> None:
    now = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    replace_performance_data(db_session)
    complete_projection(engine)

    snapshot = PerformanceMonitor(engine).refresh(now=now)

    assert snapshot.packages_scanned == 2
    assert snapshot.packages_failed >= 1
    assert snapshot.packages_dead_lettered == 1
    assert snapshot.packages_above_production_threshold == 1
    assert snapshot.packages_reported == 1


def test_performance_monitor_removes_stale_rule_labels(
    db_session: Session,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replace_performance_data(db_session)
    complete_projection(engine)
    monitor = PerformanceMonitor(engine)
    monitor.refresh()
    remove = Mock(wraps=rule_hits.remove)
    monkeypatch.setattr(rule_hits, "remove", remove)
    with db_session.begin():
        db_session.execute(update(Rule).where(Rule.name == "metrics-rule").values(name="renamed-metrics-rule"))

    snapshot = monitor.refresh()

    remove.assert_called_once_with("metrics-rule")
    assert snapshot.rule_hits["renamed-metrics-rule"] == 2


def test_rule_performance_endpoint_includes_full_rule_names(
    db_session: Session,
    engine: Engine,
) -> None:
    now = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    replace_performance_data(db_session)
    complete_projection(engine)
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
    complete_projection(engine)
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
