from datetime import datetime, timedelta
from math import isclose

from sqlalchemy.orm import Session

from mainframe.endpoints.stats import get_stats
from mainframe.models.orm import DownloadURL, Rule, Scan, Status


def test_stats(db_session: Session):
    scan = Scan(
        name="c",
        version="1.0.0",
        status=Status.FINISHED,
        score=5,
        inspector_url="test inspector url",
        rules=[Rule(name="test rule")],
        download_urls=[DownloadURL(url="test download url")],
        queued_at=datetime.now() - timedelta(seconds=60),
        queued_by="remmy",
        pending_at=datetime.now() - timedelta(seconds=30),
        pending_by="remmy",
        finished_at=datetime.now(),
        finished_by="remmy",
        reported_at=None,
        reported_by=None,
        fail_reason=None,
        commit_hash="test commit hash",
    )
    with db_session.begin():
        db_session.add(scan)

    stats = get_stats(db_session)
    assert stats.ingested == 1
    assert isclose(stats.average_scan_time, 30, rel_tol=0.01)  # float precision is ridiculous
    assert stats.failed == 0
