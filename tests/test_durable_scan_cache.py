import datetime as dt
import uuid
from collections import deque
from unittest.mock import MagicMock

import anyio
import httpx
import pytest
from fastapi import FastAPI, HTTPException
from prometheus_client import REGISTRY
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from mainframe import scan_cache
from mainframe.constants import mainframe_settings
from mainframe.dependencies import get_rules
from mainframe.endpoints.scan_cache import lookup_cache, write_cache
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import OpenGrepScan, Scan, ScanCacheEntry, ScanCacheNamespace, Status
from mainframe.models.scan_cache import CacheContext, CacheKey, CacheLease, CacheLookup, CacheValue, CacheWrite
from mainframe.rules import Rules


def context(rules_state: Rules, **changes: object) -> CacheContext:
    return CacheContext(
        scanner="yara",
        rules_commit=rules_state.rules_commit,
        rules_digest=scan_cache.rules_digest(rules_state.rules),
        engine_digest="a" * 64,
    ).model_copy(update=changes)


def value(digest: str = "1", result: str = "[]", language: str = "") -> CacheValue:
    return CacheValue(file_digest=digest * 64, language=language, result=result)


def test_rules_engine_language_and_content_are_separate(db_session: Session, rules_state: Rules) -> None:
    ctx = context(rules_state)
    with db_session.begin():
        assert scan_cache.store(db_session, ctx, [value()]).inserted == 1
    with db_session.begin():
        for changed in [
            ctx.model_copy(update={"engine_digest": "b" * 64}),
            ctx.model_copy(update={"rules_digest": "b" * 64}),
            ctx.model_copy(update={"rules_commit": "new"}),
            ctx.model_copy(update={"scanner": "opengrep"}),
        ]:
            assert not scan_cache.lookup(db_session, CacheLookup(context=changed, keys=[value()])).entries
        assert not scan_cache.lookup(
            db_session, CacheLookup(context=ctx, keys=[value("2"), value(language="py")])
        ).entries
        assert scan_cache.lookup(db_session, CacheLookup(context=ctx, keys=[value()])).entries == [value()]
    for changed in [ctx.model_copy(update={"rules_commit": "new"}), ctx.model_copy(update={"rules_digest": "b" * 64})]:
        with pytest.raises(HTTPException, match="Cache rules differ"):
            scan_cache.validate_context(changed, rules_state)


def test_recent_hits_and_duplicate_writes_do_not_update_rows(db_session: Session, rules_state: Rules) -> None:
    ctx = context(rules_state)
    with db_session.begin():
        scan_cache.store(db_session, ctx, [value()])
    with db_session.begin():
        before = db_session.execute(text("SELECT xmin::text, expires_at FROM scan_cache_entries")).one()
        assert scan_cache.store(db_session, ctx, [value(), value()]).inserted == 0
        scan_cache.lookup(db_session, CacheLookup(context=ctx, keys=[value()]))
    with db_session.begin():
        assert db_session.execute(text("SELECT xmin::text, expires_at FROM scan_cache_entries")).one() == before
        generation = db_session.get(ScanCacheNamespace, ctx.namespace())
        assert generation is not None
        assert generation.entry_count == 1
        assert generation.payload_bytes == 2


@pytest.mark.parametrize("scanner", ["yara", "opengrep"])
def test_hits_renew_only_due_valid_keys(db_session: Session, rules_state: Rules, scanner: str) -> None:
    ctx = context(rules_state, scanner=scanner)
    other = ctx.model_copy(update={"engine_digest": "b" * 64})
    now = dt.datetime.now(dt.UTC)
    due = now + dt.timedelta(hours=22)
    with db_session.begin():
        scan_cache.store(db_session, ctx, [value(), value("2"), value("3"), value("4"), value(language="py")])
        scan_cache.store(db_session, other, [value()])
        for row in db_session.scalars(select(ScanCacheEntry)):
            row.expires_at = due
            if row.file_digest == bytes.fromhex("3" * 64):
                row.expires_at = now - dt.timedelta(seconds=1)
            if row.file_digest == bytes.fromhex("4" * 64):
                row.quarantined = True
    db_session.expunge_all()
    with db_session.begin():
        reply = scan_cache.lookup(db_session, CacheLookup(context=ctx, keys=[value(), value("3"), value("4")]))
        assert reply.entries == [value()]
    db_session.expunge_all()
    with db_session.begin():
        rows = list(db_session.scalars(select(ScanCacheEntry)))
        for row in rows:
            if row.namespace == ctx.namespace() and row.file_digest == bytes.fromhex("1" * 64) and not row.language:
                assert (
                    now + dt.timedelta(hours=24) <= row.expires_at <= dt.datetime.now(dt.UTC) + dt.timedelta(hours=24)
                )
                assert row.result == "[]"
            elif row.file_digest != bytes.fromhex("3" * 64):
                assert row.expires_at == due
        generation = db_session.get(ScanCacheNamespace, ctx.namespace())
        assert generation is not None
        assert (generation.entry_count, generation.payload_bytes) == (5, 10)
        before = db_session.execute(text("SELECT xmin::text, expires_at FROM scan_cache_entries ORDER BY 2, 1")).all()
        scan_cache.lookup(db_session, CacheLookup(context=ctx, keys=[value()]))
    with db_session.begin():
        assert (
            db_session.execute(text("SELECT xmin::text, expires_at FROM scan_cache_entries ORDER BY 2, 1")).all()
            == before
        )


def test_renewal_contention_preserves_hits(
    db_session: Session, rules_state: Rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = context(rules_state)
    due = dt.datetime.now(dt.UTC) + dt.timedelta(hours=22)
    with db_session.begin():
        scan_cache.store(db_session, ctx, [value()])
        db_session.execute(text("UPDATE scan_cache_entries SET expires_at = :due"), {"due": due})
    monkeypatch.setattr(scan_cache, "writer_lock", MagicMock(return_value=False))
    with db_session.begin():
        assert scan_cache.lookup(db_session, CacheLookup(context=ctx, keys=[value()])).entries == [value()]
        assert db_session.scalar(select(ScanCacheEntry.expires_at)) == due


def test_renewal_rechecks_revocation_and_short_ttl(
    db_session: Session, rules_state: Rules, monkeypatch: pytest.MonkeyPatch
):
    ctx = context(rules_state)
    now = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(mainframe_settings, "scan_cache_ttl_seconds", 60)
    with db_session.begin():
        scan_cache.store(db_session, ctx, [value()])
        row = db_session.scalar(select(ScanCacheEntry))
        assert row is not None
        row.expires_at = now + dt.timedelta(seconds=20)
    with db_session.begin():
        scan_cache.renew_hits(db_session, ctx, [row], now)
    db_session.expire_all()
    with db_session.begin():
        assert row.expires_at == now + dt.timedelta(seconds=60)
        generation = db_session.get(ScanCacheNamespace, ctx.namespace())
        assert generation is not None
        generation.revoked = True
    with db_session.begin():
        # Simulate revocation committed between the initial read and renewal.
        scan_cache.renew_hits(db_session, ctx, [row], now + dt.timedelta(seconds=40))
        assert scan_cache.lookup(db_session, CacheLookup(context=ctx, keys=[value()])).revoked
    db_session.expire_all()
    with db_session.begin():
        assert row.expires_at == now + dt.timedelta(seconds=60)


def test_renewal_metric_counts_only_committed_updates(db_session: Session, rules_state: Rules) -> None:
    def renewal_count() -> float:
        return REGISTRY.get_sample_value("scanner_cache_rows_renewed_total", {"scanner": "yara"}) or 0

    ctx = context(rules_state)
    due = dt.datetime.now(dt.UTC) + dt.timedelta(hours=22)
    with db_session.begin():
        scan_cache.store(db_session, ctx, [value()])
        db_session.execute(text("UPDATE scan_cache_entries SET expires_at = :due"), {"due": due})
    before = renewal_count()
    connection = scan_cache.cache_session()
    session = next(connection)
    assert scan_cache.lookup(session, CacheLookup(context=ctx, keys=[value()])).entries == [value()]
    assert renewal_count() == before
    with pytest.raises(HTTPException) as failure:
        connection.throw(SQLAlchemyError("transaction failed before commit"))
    assert failure.value.status_code == 503
    assert renewal_count() == before
    with db_session.begin():
        assert db_session.scalar(select(ScanCacheEntry.expires_at)) == due
    connection = scan_cache.cache_session()
    session = next(connection)
    scan_cache.lookup(session, CacheLookup(context=ctx, keys=[value()]))
    with pytest.raises(StopIteration):
        next(connection)
    assert renewal_count() == before + 1


def test_quotas_bound_all_namespaces(db_session: Session, rules_state: Rules, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mainframe_settings, "scan_cache_max_entries", 2)
    monkeypatch.setattr(mainframe_settings, "scan_cache_max_bytes", 4)
    ctx = context(rules_state)
    with db_session.begin():
        assert scan_cache.store(db_session, ctx, [value(), value("2"), value("3")]).inserted == 2
        assert (
            scan_cache.store(db_session, ctx.model_copy(update={"engine_digest": "b" * 64}), [value("4")]).inserted == 0
        )
        assert db_session.scalar(select(func.count()).select_from(ScanCacheEntry)) == 2
    monkeypatch.setattr(mainframe_settings, "scan_cache_max_entries", 100)
    with db_session.begin():
        assert scan_cache.store(db_session, ctx, [value("4")]).inserted == 0


def test_expiry_is_bounded_and_revocation_survives_sessions(
    db_session: Session, rules_state: Rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = context(rules_state)
    with db_session.begin():
        scan_cache.store(db_session, ctx, [value(), value("2")])
        for row in db_session.scalars(select(ScanCacheEntry)):
            row.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    monkeypatch.setattr(scan_cache, "CLEANUP_BATCH", 1)
    with db_session.begin():
        assert not scan_cache.lookup(db_session, CacheLookup(context=ctx, keys=[value()])).entries
        assert scan_cache.expire_entries(db_session, "yara", ctx.rules_commit) == 1
        generation = db_session.get(ScanCacheNamespace, ctx.namespace())
        assert generation is not None
        assert generation.entry_count == 1
        generation.revoked = True
    db_session.expunge_all()
    with db_session.begin():
        assert scan_cache.lookup(db_session, CacheLookup(context=ctx, keys=[value()])).revoked
        assert scan_cache.store(db_session, ctx, [value("3")]).inserted == 0
        assert scan_cache.expire_entries(db_session, "yara", "new-rules") == 1
        assert db_session.get(ScanCacheNamespace, ctx.namespace()) is None


def test_routes_require_current_lease_and_support_revocation(
    db_session: Session, rules_state: Rules, auth: AuthenticationData
) -> None:
    ctx = context(rules_state)
    lease = CacheLease(name="cache-test", version="1", attempt=1, assignment_id=uuid.uuid4())
    with db_session.begin():
        with pytest.raises(HTTPException):
            scan_cache.validate_lease(db_session, "yara", lease, auth.subject)
        db_session.add(
            Scan(
                name=lease.name,
                queued_by="test",
                version=lease.version,
                status=Status.PENDING,
                assignment_id=lease.assignment_id,
                attempt_count=1,
                pending_by=auth.subject,
            )
        )
    with db_session.begin():
        request = CacheWrite(context=ctx, lease=lease, entries=[value()])
        assert write_cache(request, db_session, rules_state, auth).inserted == 1
        assert lookup_cache(CacheLookup(context=ctx, keys=[value()]), db_session, rules_state).entries
        write_cache(request.model_copy(update={"revoke": True}), db_session, rules_state, auth)
        assert lookup_cache(CacheLookup(context=ctx, keys=[value()]), db_session, rules_state).revoked


def test_wire_limits_and_hash_validation():
    with pytest.raises(ValidationError):
        CacheKey(file_digest="not-a-cryptographic-digest")
    with pytest.raises(ValidationError):
        value(result="{}")
    with pytest.raises(ValidationError):
        value(result='["' + "é" * 10000 + '"]')


def test_cache_admission_and_isolated_connection(monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setattr(mainframe_settings, "scan_cache_enabled", False)
    with pytest.raises(HTTPException) as hidden:
        scan_cache.require_cache()
    assert hidden.value.status_code == 404
    monkeypatch.setattr(mainframe_settings, "scan_cache_enabled", True)
    monkeypatch.setattr(scan_cache, "_recent_requests", deque[float]())
    for _ in range(scan_cache.MAX_REQUESTS_PER_SECOND):
        scan_cache.require_cache()
    with pytest.raises(HTTPException) as limited:
        scan_cache.require_cache()
    assert limited.value.status_code == 429
    monkeypatch.setattr(scan_cache.time, "monotonic", lambda: float("inf"))
    scan_cache.require_cache()
    connection = scan_cache.cache_session()
    session = next(connection)
    assert session.scalar(text("SHOW statement_timeout")) == "200ms"
    assert session.scalar(text("SHOW lock_timeout")) == "25ms"
    with pytest.raises(HTTPException) as busy:
        next(scan_cache.cache_session())
    assert busy.value.status_code == 503
    with pytest.raises(StopIteration):
        next(connection)
    connection = scan_cache.cache_session()
    next(connection)
    with pytest.raises(HTTPException) as unavailable:
        connection.throw(SQLAlchemyError("test database outage"))
    assert unavailable.value.status_code == 503


def test_cache_recovers_after_commit_timeout() -> None:
    transaction = scan_cache.cache_session()
    session = next(transaction)
    old_backend = session.scalar(text("SELECT pg_backend_pid()"))
    session.execute(text("CREATE TEMP TABLE cache_commit_test (id integer) ON COMMIT DROP"))
    session.execute(
        text(
            "CREATE FUNCTION pg_temp.delay_cache_commit() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN RAISE EXCEPTION 'canceling statement due to statement timeout' "
            "USING ERRCODE = '57014'; END $$"
        )
    )
    session.execute(
        text(
            "CREATE CONSTRAINT TRIGGER delay_cache_commit AFTER INSERT ON cache_commit_test "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION pg_temp.delay_cache_commit()"
        )
    )
    session.execute(text("INSERT INTO cache_commit_test VALUES (1)"))
    with pytest.raises(HTTPException) as error:
        next(transaction)
    assert error.value.status_code == 503
    recovered = scan_cache.cache_session()
    session = next(recovered)
    assert session.scalar(text("SELECT pg_backend_pid()")) != old_backend
    assert session.scalar(text("SHOW statement_timeout")) == "200ms"
    assert session.scalar(text("SELECT 1")) == 1
    with pytest.raises(StopIteration):
        next(recovered)


def test_maintenance_and_namespace_budget(
    db_session: Session, rules_state: Rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = context(rules_state)
    monkeypatch.setattr(scan_cache, "MAX_NAMESPACES", 1)
    with db_session.begin():
        assert scan_cache.store(db_session, ctx, [value()]).inserted == 1
        assert (
            scan_cache.store(db_session, ctx.model_copy(update={"engine_digest": "b" * 64}), [value("2")]).skipped == 1
        )
    monkeypatch.setattr(mainframe_settings, "scan_cache_enabled", False)
    scan_cache.maintain_cache(ctx.rules_commit)
    monkeypatch.setattr(mainframe_settings, "scan_cache_enabled", True)
    scan_cache.maintain_cache(ctx.rules_commit)


def test_contended_writer_bypasses_cache(
    db_session: Session, rules_state: Rules, auth: AuthenticationData, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scan_cache, "writer_lock", MagicMock(return_value=False))
    with db_session.begin():
        assert scan_cache.expire_entries(db_session, "yara", "rules") == 0
    monkeypatch.setattr(scan_cache, "validate_lease", MagicMock(return_value=None))
    with db_session.begin(), pytest.raises(HTTPException) as busy:
        write_cache(
            CacheWrite(
                context=context(rules_state),
                lease=CacheLease(name="test", version="1", assignment_id=uuid.uuid4(), attempt=1),
                entries=[],
            ),
            db_session,
            rules_state,
            auth,
        )
    assert busy.value.status_code == 503


def test_shadow_lease_is_separate(db_session: Session, auth: AuthenticationData) -> None:

    lease = CacheLease(name="shadow-cache", version="1", assignment_id=uuid.uuid4(), attempt=1)
    with db_session.begin():
        scan = Scan(name=lease.name, version=lease.version, queued_by="test", status=Status.FINISHED)
        db_session.add(scan)
        db_session.flush()
        db_session.add(
            OpenGrepScan(
                scan_id=scan.scan_id,
                queued_by="test",
                queued_at=dt.datetime.now(dt.UTC),
                status=Status.PENDING,
                pending_by=auth.subject,
                attempt_count=1,
                assignment_id=lease.assignment_id,
            )
        )
    with db_session.begin():
        scan_cache.validate_lease(db_session, "opengrep", lease, auth.subject)
        with pytest.raises(HTTPException):
            scan_cache.validate_lease(db_session, "yara", lease, auth.subject)


def test_batch_payload_bound(rules_state: Rules) -> None:
    with pytest.raises(ValidationError, match="512 KiB"):
        CacheWrite(
            context=context(rules_state),
            lease=CacheLease(name="test", version="1", assignment_id=uuid.uuid4(), attempt=1),
            entries=[value(result='["' + "x" * 16000 + '"]')] * 33,
        )


def test_physical_disk_admission_limit(
    db_session: Session, rules_state: Rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mainframe_settings, "scan_cache_max_disk_bytes", 1)
    with db_session.begin():
        assert scan_cache.store(db_session, context(rules_state), [value()]).skipped == 1


def test_http_cache_round_trip_commits_before_response(
    db_session: Session,
    rules_state: Rules,
    auth: AuthenticationData,
    app_without_auth: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mainframe_settings, "scan_cache_enabled", True)
    monkeypatch.setattr(scan_cache, "_recent_requests", deque[float]())
    lease = CacheLease(name="http-cache", version="1", assignment_id=uuid.uuid4(), attempt=1)
    with db_session.begin():
        db_session.add(
            Scan(
                name=lease.name,
                version=lease.version,
                queued_by="test",
                status=Status.PENDING,
                pending_by=auth.subject,
                assignment_id=lease.assignment_id,
                attempt_count=1,
            )
        )

    def get_test_rules() -> Rules:
        return rules_state

    app_without_auth.dependency_overrides[get_rules] = get_test_rules

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_without_auth), base_url="http://test"
        ) as client:
            ctx = context(rules_state)
            written = await client.post(
                "/scan-cache/write",
                json=CacheWrite(context=ctx, lease=lease, entries=[value()]).model_dump(mode="json"),
            )
            assert written.status_code == 200
            assert written.json()["inserted"] == 1
            # A new database session observes the write immediately after HTTP completion.
            with db_session.begin():
                assert db_session.scalar(select(func.count()).select_from(ScanCacheEntry)) == 1
                due = dt.datetime.now(dt.UTC) + dt.timedelta(hours=22)
                db_session.execute(text("UPDATE scan_cache_entries SET expires_at = :due"), {"due": due})
            response = await client.post(
                "/scan-cache/lookup", json=CacheLookup(context=ctx, keys=[value()]).model_dump(mode="json")
            )
            assert response.status_code == 200
            assert response.json()["entries"][0]["result"] == "[]"
            with db_session.begin():
                expires = db_session.scalar(select(ScanCacheEntry.expires_at))
                assert expires is not None
                assert expires > due + dt.timedelta(hours=1)
            request = CacheWrite(context=ctx, lease=lease, entries=[], quarantine=[value()])
            quarantined = await client.post("/scan-cache/write", json=request.model_dump(mode="json"))
            assert quarantined.status_code == 200
            assert quarantined.json()["quarantined"] == 1
            with db_session.begin():
                assert db_session.scalar(select(ScanCacheEntry.quarantined)) is True
            response = await client.post(
                "/scan-cache/lookup", json=CacheLookup(context=ctx, keys=[value()]).model_dump(mode="json")
            )
            assert response.json() == {"revoked": False, "entries": []}
            stale = request.model_copy(update={"lease": lease.model_copy(update={"attempt": 2})})
            assert (await client.post("/scan-cache/write", json=stale.model_dump(mode="json"))).status_code == 409

    try:
        anyio.run(exercise)
    finally:
        app_without_auth.dependency_overrides.pop(get_rules)


def test_quarantine_preserves_other_keys_evidence_and_quotas(db_session: Session, rules_state: Rules) -> None:
    ctx = context(rules_state)
    other = ctx.model_copy(update={"engine_digest": "b" * 64})
    with db_session.begin():
        scan_cache.store(db_session, ctx, [value(result='["suspect"]'), value("2"), value(language="py")])
        scan_cache.store(db_session, other, [value()])
        before = db_session.execute(
            select(ScanCacheNamespace.entry_count, ScanCacheNamespace.payload_bytes).where(
                ScanCacheNamespace.namespace == ctx.namespace()
            )
        ).one()
        assert scan_cache.quarantine(db_session, ctx, [value(), value("3")]).quarantined == 1
    db_session.expire_all()
    with db_session.begin():
        assert scan_cache.quarantine(db_session, ctx, [value()]).quarantined == 0
        assert scan_cache.store(db_session, ctx, [value()]).inserted == 0
        reply = scan_cache.lookup(
            db_session, CacheLookup(context=ctx, keys=[value(), value("2"), value(language="py")])
        )
        assert not reply.revoked
        assert {(r.file_digest, r.language) for r in reply.entries} == {("2" * 64, ""), ("1" * 64, "py")}
        assert scan_cache.lookup(db_session, CacheLookup(context=other, keys=[value()])).entries
        row = db_session.get(ScanCacheEntry, (ctx.namespace(), bytes.fromhex("1" * 64), ""))
        assert row is not None
        assert row.quarantined
        assert row.result == '["suspect"]'
        assert (
            db_session.execute(
                select(ScanCacheNamespace.entry_count, ScanCacheNamespace.payload_bytes).where(
                    ScanCacheNamespace.namespace == ctx.namespace()
                )
            ).one()
            == before
        )
        row.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        db_session.flush()
        assert scan_cache.expire_entries(db_session, "yara", ctx.rules_commit) == 1


def test_quarantine_requests_cannot_mix_operations(rules_state: Rules) -> None:
    ctx = context(rules_state)
    lease = CacheLease(name="test", version="1", assignment_id=uuid.uuid4(), attempt=1)
    with pytest.raises(ValidationError, match="Quarantine must be separate"):
        CacheWrite(context=ctx, lease=lease, entries=[value()], quarantine=[value()])
    with pytest.raises(ValidationError, match="Quarantine must be separate"):
        CacheWrite(context=ctx, lease=lease, entries=[], revoke=True, quarantine=[value()])
    with pytest.raises(ValidationError):
        CacheWrite(context=ctx, lease=lease, entries=[], quarantine=[value()] * 129)
