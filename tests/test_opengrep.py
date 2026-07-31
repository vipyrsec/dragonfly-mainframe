import datetime as dt
import uuid

import pytest
from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from mainframe.constants import Mainframe, validate_opengrep_shadow_environment
from mainframe.endpoints.opengrep import (
    acknowledge_opengrep_result,
    checkpoint_opengrep_publication,
    get_opengrep_jobs,
    get_opengrep_rules,
    get_unpublished_opengrep_results,
    heartbeat_opengrep_publication,
    require_opengrep_shadow,
    submit_opengrep_result,
)
from mainframe.endpoints.package import queue_package
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import DownloadURL, OpenGrepScan, Scan, Status
from mainframe.models.schemas import (
    OpenGrepFinding,
    OpenGrepPublicationClaim,
    OpenGrepPublicationProgress,
    OpenGrepScanResult,
    OpenGrepScanResultFail,
    PackageSpecifier,
)
from mainframe.pypi import PyPIClient
from mainframe.rules import Rules


def queued_shadow(db_session: Session) -> Scan:
    scan = Scan(
        name="shadow-example",
        version="1.0.0",
        status=Status.QUEUED,
        queued_by="test",
        download_urls=[DownloadURL(url="https://files.example/shadow-example.whl")],
    )
    with db_session.begin():
        db_session.execute(update(Scan).values(status=Status.FINISHED))
        db_session.add(scan)
        db_session.flush([scan])
        db_session.add(
            OpenGrepScan(
                scan_id=scan.scan_id,
                queued_at=scan.queued_at or dt.datetime.now(dt.UTC),
                queued_by=scan.queued_by,
            )
        )
    return scan


def test_shadow_configuration_is_staging_only() -> None:
    with pytest.raises(ValueError, match="requires ENVIRONMENT=staging"):
        Mainframe(
            dragonfly_github_token="test",
            environment="production",
            opengrep_shadow_enabled=True,
        )

    settings = Mainframe(
        dragonfly_github_token="test",
        environment="staging",
        opengrep_shadow_enabled=True,
    )

    assert settings.opengrep_shadow_enabled


def test_disabled_shadow_api_is_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mainframe.constants.mainframe_settings.opengrep_shadow_enabled", False)

    with pytest.raises(HTTPException) as error:
        require_opengrep_shadow()

    assert error.value.status_code == status.HTTP_404_NOT_FOUND


def test_shadow_environment_requires_staging_access_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mainframe.constants.mainframe_settings.opengrep_shadow_enabled", False)
    validate_opengrep_shadow_environment()

    monkeypatch.setattr("mainframe.constants.mainframe_settings.opengrep_shadow_enabled", True)
    monkeypatch.setattr(
        "mainframe.constants.cf_access_settings.audience",
        "https://dragonfly.vipyrsec.com",
    )

    with pytest.raises(RuntimeError, match="staging Cloudflare Access audience"):
        validate_opengrep_shadow_environment()

    monkeypatch.setattr(
        "mainframe.constants.cf_access_settings.audience",
        "https://dragonfly-staging.vipyrsec.com",
    )
    validate_opengrep_shadow_environment()


def test_opengrep_rules_are_separate() -> None:
    state = Rules(
        rules_commit="rules-commit",
        rules={"yara": "rule yara"},
        opengrep_rules={"python/payload.yml": "rules: []"},
    )

    response = get_opengrep_rules(state)

    assert response.hash == "rules-commit"
    assert response.rules == {"python/payload.yml": "rules: []"}


def test_queue_creates_additive_shadow_work_when_enabled(
    db_session: Session,
    auth: AuthenticationData,
    pypi_client: PyPIClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mainframe.constants.mainframe_settings.opengrep_shadow_enabled", True)

    response = queue_package(
        PackageSpecifier(name="new-shadow-package", version="1.0.0"),
        db_session,
        auth,
        pypi_client,
    )

    with db_session.begin():
        canonical = db_session.get(Scan, uuid.UUID(response.id))
        shadow = db_session.get(OpenGrepScan, uuid.UUID(response.id))
        assert canonical is not None
        assert canonical.status == Status.QUEUED
        assert shadow is not None
        assert shadow.status == Status.QUEUED


def test_shadow_result_does_not_mutate_canonical_scan(
    db_session: Session,
    auth: AuthenticationData,
    rules_state: Rules,
) -> None:
    scan = queued_shadow(db_session)
    jobs = get_opengrep_jobs(db_session, auth, rules_state)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.distributions == ["https://files.example/shadow-example.whl"]
    finding = OpenGrepFinding(
        rule_id="python-flow-example",
        path="example/module.py",
        start_line=3,
        end_line=7,
        message="Example behavioral flow.",
        severity="ERROR",
        evidence="flow",
        confidence="high",
        execution_context="unresolved",
        inspector_url="https://inspector.example/project/example/module.py",
    )
    submit_opengrep_result(
        OpenGrepScanResult(
            name=job.name,
            version=job.version,
            commit=job.hash,
            duration_ms=42,
            findings=[finding],
            attempt=job.attempt,
            assignment_id=job.assignment_id,
        ),
        db_session,
        auth,
    )

    unpublished = get_unpublished_opengrep_results(db_session)

    assert len(unpublished) == 1
    assert unpublished[0].scan_id == scan.scan_id
    assert unpublished[0].findings == [finding]
    with db_session.begin():
        canonical = db_session.get(Scan, scan.scan_id)
        shadow = db_session.get(OpenGrepScan, scan.scan_id)
        assert canonical is not None
        assert canonical.status == Status.QUEUED
        assert canonical.score is None
        assert canonical.rules == []
        assert shadow is not None
        assert shadow.status == Status.FINISHED
        assert shadow.duration_ms == 42

    claim = OpenGrepPublicationClaim(publication_id=unpublished[0].publication_id)
    acknowledgement = acknowledge_opengrep_result(scan.scan_id, claim, db_session)

    assert acknowledgement.published_at is not None
    assert get_unpublished_opengrep_results(db_session) == []


def test_shadow_rejects_stale_assignment(
    db_session: Session,
    auth: AuthenticationData,
    rules_state: Rules,
) -> None:
    queued_shadow(db_session)
    job = get_opengrep_jobs(db_session, auth, rules_state)[0]
    result = OpenGrepScanResult(
        name=job.name,
        version=job.version,
        commit=job.hash,
        duration_ms=1,
        findings=[],
        attempt=job.attempt,
        assignment_id=uuid.uuid4(),
    )

    with pytest.raises(HTTPException) as error:
        submit_opengrep_result(result, db_session, auth)

    assert error.value.status_code == status.HTTP_409_CONFLICT


def test_shadow_failure_is_published_without_mutating_canonical_scan(
    db_session: Session,
    auth: AuthenticationData,
    rules_state: Rules,
) -> None:
    scan = queued_shadow(db_session)
    job = get_opengrep_jobs(db_session, auth, rules_state)[0]

    submit_opengrep_result(
        OpenGrepScanResultFail(
            name=job.name,
            version=job.version,
            duration_ms=7,
            reason="bounded test failure",
            attempt=job.attempt,
            assignment_id=job.assignment_id,
        ),
        db_session,
        auth,
    )

    unpublished = get_unpublished_opengrep_results(db_session)

    assert len(unpublished) == 1
    assert unpublished[0].status == "failed"
    assert unpublished[0].fail_reason == "bounded test failure"
    assert unpublished[0].findings == []
    with db_session.begin():
        canonical = db_session.get(Scan, scan.scan_id)
        assert canonical is not None
        assert canonical.status == Status.QUEUED


def test_shadow_result_requires_an_existing_package(
    db_session: Session,
    auth: AuthenticationData,
) -> None:
    result = OpenGrepScanResult(
        name="missing-shadow-package",
        version="1.0.0",
        commit="rules-commit",
        duration_ms=1,
        findings=[],
        attempt=1,
        assignment_id=uuid.uuid4(),
    )

    with pytest.raises(HTTPException) as error:
        submit_opengrep_result(result, db_session, auth)

    assert error.value.status_code == status.HTTP_404_NOT_FOUND


def test_terminal_shadow_result_requires_finished_timestamp(
    db_session: Session,
) -> None:
    scan = queued_shadow(db_session)
    scan_id = scan.scan_id
    with db_session.begin():
        shadow = db_session.get(OpenGrepScan, scan_id)
        assert shadow is not None
        shadow.status = Status.FINISHED
        shadow.finished_at = None

    with pytest.raises(RuntimeError, match="missing finished_at"):
        get_unpublished_opengrep_results(db_session)


def test_shadow_acknowledgement_rejects_missing_and_incomplete_results(
    db_session: Session,
) -> None:
    claim = OpenGrepPublicationClaim(publication_id=uuid.uuid4())
    with pytest.raises(HTTPException) as missing_error:
        acknowledge_opengrep_result(uuid.uuid4(), claim, db_session)
    assert missing_error.value.status_code == status.HTTP_404_NOT_FOUND

    scan = queued_shadow(db_session)
    with pytest.raises(HTTPException) as incomplete_error:
        acknowledge_opengrep_result(scan.scan_id, claim, db_session)
    assert incomplete_error.value.status_code == status.HTTP_409_CONFLICT


def test_shadow_acknowledgement_is_idempotent(
    db_session: Session,
) -> None:
    scan = queued_shadow(db_session)
    with db_session.begin():
        shadow = db_session.get(OpenGrepScan, scan.scan_id)
        assert shadow is not None
        shadow.status = Status.FINISHED
        shadow.finished_at = dt.datetime.now(dt.UTC)

    result = get_unpublished_opengrep_results(db_session)[0]
    claim = OpenGrepPublicationClaim(publication_id=result.publication_id)
    first = acknowledge_opengrep_result(scan.scan_id, claim, db_session)
    second = acknowledge_opengrep_result(scan.scan_id, claim, db_session)
    checkpoint_opengrep_publication(
        scan.scan_id,
        OpenGrepPublicationProgress(
            publication_id=result.publication_id,
            published_chunks=0,
        ),
        db_session,
    )

    assert second.published_at == first.published_at


def test_shadow_results_are_claimed_once_until_the_lease_expires(
    db_session: Session,
    auth: AuthenticationData,
    rules_state: Rules,
) -> None:
    queued_shadow(db_session)
    job = get_opengrep_jobs(db_session, auth, rules_state)[0]
    submit_opengrep_result(
        OpenGrepScanResult(
            name=job.name,
            version=job.version,
            commit=job.hash,
            duration_ms=1,
            findings=[],
            attempt=job.attempt,
            assignment_id=job.assignment_id,
        ),
        db_session,
        auth,
    )

    first = get_unpublished_opengrep_results(db_session)
    second = get_unpublished_opengrep_results(db_session)

    assert len(first) == 1
    assert second == []
    assert first[0].publication_id is not None


def test_shadow_publication_heartbeat_prevents_lease_takeover(
    db_session: Session,
) -> None:
    scan = queued_shadow(db_session)
    with db_session.begin():
        shadow = db_session.get(OpenGrepScan, scan.scan_id)
        assert shadow is not None
        shadow.status = Status.FINISHED
        shadow.finished_at = dt.datetime.now(dt.UTC)
    result = get_unpublished_opengrep_results(db_session)[0]
    with db_session.begin():
        shadow = db_session.get(OpenGrepScan, scan.scan_id)
        assert shadow is not None
        shadow.publication_claimed_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)

    heartbeat_opengrep_publication(
        scan.scan_id,
        OpenGrepPublicationClaim(publication_id=result.publication_id),
        db_session,
    )

    assert get_unpublished_opengrep_results(db_session) == []


def test_shadow_publication_progress_is_monotonic_and_resumable(
    db_session: Session,
) -> None:
    scan = queued_shadow(db_session)
    scan_id = scan.scan_id
    with db_session.begin():
        shadow = db_session.get(OpenGrepScan, scan_id)
        assert shadow is not None
        shadow.status = Status.FINISHED
        shadow.finished_at = dt.datetime.now(dt.UTC)
    result = get_unpublished_opengrep_results(db_session)[0]
    progress = OpenGrepPublicationProgress(
        publication_id=result.publication_id,
        discord_message_id=100,
        discord_thread_id=200,
        published_chunks=2,
    )

    checkpoint_opengrep_publication(scan_id, progress, db_session)
    with db_session.begin():
        shadow = db_session.get(OpenGrepScan, scan_id)
        assert shadow is not None
        assert shadow.discord_message_id == 100
        assert shadow.discord_thread_id == 200
        assert shadow.published_chunks == 2

    backwards = progress.model_copy(update={"published_chunks": 1})
    with pytest.raises(HTTPException, match="cannot move backwards"):
        checkpoint_opengrep_publication(scan_id, backwards, db_session)

    changed_message = progress.model_copy(update={"discord_message_id": 101})
    with pytest.raises(HTTPException, match="discord_message_id cannot change"):
        checkpoint_opengrep_publication(scan_id, changed_message, db_session)


def test_shadow_publication_rejects_a_stale_claim(
    db_session: Session,
) -> None:
    scan = queued_shadow(db_session)
    with db_session.begin():
        shadow = db_session.get(OpenGrepScan, scan.scan_id)
        assert shadow is not None
        shadow.status = Status.FINISHED
        shadow.finished_at = dt.datetime.now(dt.UTC)
    get_unpublished_opengrep_results(db_session)
    stale = OpenGrepPublicationProgress(
        publication_id=uuid.uuid4(),
        published_chunks=0,
    )

    with pytest.raises(HTTPException, match="lease is stale"):
        checkpoint_opengrep_publication(scan.scan_id, stale, db_session)
