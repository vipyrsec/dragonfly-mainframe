import random

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from mainframe.constants import mainframe_settings
from mainframe.models.orm import Scan


def test_get_scans(api_url: str, db_session: Session):
    query = select(Scan).order_by(Scan.queued_at)

    all_scans = db_session.scalars(query).all()

    # Pick a random package and query all that have been queued after it
    random_scan = random.choice(all_scans)
    print("Querying packages since", random_scan.queued_at.isoformat())
    since = int(random_scan.queued_at.timestamp())
    res = requests.get(f"{api_url}/scans", params=dict(since=since))
    json = res.json()

    # Check that the `all_scans` list is accurate
    all_package_specifiers = {
        (scan.name, scan.version)
        for scan in all_scans
        if (scan.finished_at is not None) and (scan.finished_at >= random_scan.queued_at)
    }
    assert len(all_package_specifiers) == len(json["all_scans"])
    assert all((scan["name"], scan["version"]) in all_package_specifiers for scan in json["all_scans"])

    # Check that the `malicious_packages` list is accurate
    malicious_package_specifiers = {
        (scan.name, scan.version)
        for scan in all_scans
        if (scan.score is not None)
        and (scan.score >= mainframe_settings.score_threshold)
        and (scan.finished_at >= random_scan.queued_at)
    }
    assert len(malicious_package_specifiers) == len(json["malicious_packages"])
    assert all(
        (malicious_package["name"], malicious_package["version"]) in malicious_package_specifiers
        for malicious_package in json["malicious_packages"]
    )
