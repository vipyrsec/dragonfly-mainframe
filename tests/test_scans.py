import datetime
import random
import string

from fastapi.testclient import TestClient

from mainframe.constants import mainframe_settings


def _gen_random_string() -> str:
    """Generate a random string"""

    return "".join(random.choices(string.printable, k=10))


def test_get_scans(client: TestClient):
    since = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())

    res = client.post("/jobs", params=dict(batch=2))
    jobs = res.json()

    if len(jobs) == 0:
        payload = [
            dict(name=_gen_random_string(), version=_gen_random_string()),
            dict(name=_gen_random_string(), version=_gen_random_string()),
        ]
        client.post("/batch/package", json=payload)

        res = client.post("/jobs", params=dict(batch=2))
        jobs = res.json()

    for job in jobs:
        payload = dict(
            name=job["name"],
            version=job["version"],
            commit=_gen_random_string(),
            score=mainframe_settings.score_threshold + random.randint(0, 20),
            inspector_url=_gen_random_string(),
            rules_matched=[_gen_random_string() for _ in range(random.randint(0, 5))],
        )

        client.put("/package", json=payload)

    res = client.get("/scans", params=dict(since=since))
    scans = res.json()

    jobs = [dict(name=j["name"], version=j["version"]) for j in jobs]
    assert [dict(name=p["name"], version=p["version"]) for p in scans["all_scans"]] == jobs
    assert [dict(name=p["name"], version=p["version"]) for p in scans["malicious_packages"]] == jobs
