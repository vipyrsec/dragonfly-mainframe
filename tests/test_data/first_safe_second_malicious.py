from datetime import datetime

from mainframe.models.orm import Package, Rule, Scan, Status

data = [
    Package(
        name="a",
        scans=[
            Scan(
                name="a",
                version="0.1.0",
                status=Status.FINISHED,
                score=0,
                inspector_url=None,
                queued_at=datetime.fromisoformat("2023-05-12T18:00:00+00:00"),
                queued_by="remmy",
                pending_at=datetime.fromisoformat("2023-05-12T18:30:00+00:00"),
                pending_by="remmy",
                finished_at=datetime.fromisoformat("2023-05-12T19:00:00+00:00"),
                finished_by="remmy",
                reported_at=None,
                reported_by=None,
                rules=[],
                download_urls=[],
                commit_hash=None,
                fail_reason=None,
            ),
            Scan(
                name="a",
                version="0.2.0",
                status=Status.FINISHED,
                score=10,
                inspector_url="some inspector URL",
                queued_at=datetime.fromisoformat("2023-05-12T19:00:00+00:00"),
                queued_by="remmy",
                pending_at=datetime.fromisoformat("2023-05-12T19:30:00+00:00"),
                pending_by="remmy",
                finished_at=datetime.fromisoformat("2023-05-12T20:00:00+00:00"),
                finished_by="remmy",
                reported_at=None,
                reported_by=None,
                download_urls=[],
                rules=[Rule(name="test rule 1")],
                commit_hash="test commit hash",
                fail_reason=None,
            ),
        ],
    ),
]
