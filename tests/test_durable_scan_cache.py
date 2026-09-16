import datetime as dt
import uuid
from collections import deque
from unittest.mock import MagicMock

import anyio
import httpx
import pytest
from fastapi import FastAPI, HTTPException
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


def test_hits_and_duplicate_writes_do_not_update_rows(db_session: Session, rules_state: Rules) -> None:
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
            response = await client.post(
                "/scan-cache/lookup", json=CacheLookup(context=ctx, keys=[value()]).model_dump(mode="json")
            )
            assert response.status_code == 200
            assert response.json()["entries"][0]["result"] == "[]"

    try:
        anyio.run(exercise)
    finally:
        app_without_auth.dependency_overrides.pop(get_rules)
