from datetime import datetime

from mainframe.models.orm import Scan

data = [
    Scan(
        scan_id="fce0366b-0bcf-4a29-a0a7-4d4bdf3c6f61",
        name="a",
        version="0.1.0",
        score=0,
        inspector_url=None,
        finished_at=datetime.fromisoformat("2023-05-12T19:00:00+00:00"),
        reported_at=None,
        reported_by=None,
        rules=[],
    ),
    Scan(
        scan_id="df157a3c-8994-467f-a494-9d63eaf96564",
        name="b",
        version="0.1.0",
        score=0,
        inspector_url=None,
        finished_at=datetime.fromisoformat("2023-05-12T16:30:00+00:00"),
        reported_at=None,
        reported_by=None,
        rules=[],
    ),
    Scan(
        scan_id="04685768-e41d-49e4-9192-19b6d435226a",
        name="a",
        version="0.2.0",
        score=0,
        inspector_url=None,
        finished_at=datetime.fromisoformat("2023-05-12T17:30:00+00:00"),
        reported_at=None,
        reported_by=None,
        rules=[],
    ),
    Scan(
        scan_id="bbb953ca-95af-4d57-a7a5-0b656f652695",
        name="z",
        version="0.1.0",
        score=69,
        inspector_url="inspector url for package z v69",
        finished_at=datetime.fromisoformat("2023-05-12T18:30:00+00:00"),
        reported_at=None,
        reported_by=None,
        rules=[],
    ),
]
