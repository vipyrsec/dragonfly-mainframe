from datetime import datetime

from mainframe.models.orm import Rule, Scan

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
        scan_id="13e22275-9053-4490-ab80-1800789d37da",
        name="a",
        version="0.2.0",
        score=10,
        inspector_url="some inspector URL",
        finished_at=datetime.fromisoformat("2023-05-12T20:00:00+00:00"),
        reported_at=None,
        reported_by=None,
        rules=[Rule(id="50bd2157-72ef-49c9-b75c-25e0b39cae5d", name="test rule 1")],
    ),
]
