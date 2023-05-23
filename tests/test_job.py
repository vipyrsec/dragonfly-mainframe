import requests


def test_acquire_job(api_url: str):
    r = requests.post(f"{api_url}/job")
    r.raise_for_status()
    json = r.json()
    assert json["name"] == "a" and json["version"] == "0.2.0"


def test_no_jobs(api_url: str):
    requests.post(f"{api_url}/job")
    r = requests.post(f"{api_url}/job")
    r.raise_for_status()
    assert r.json()["detail"] == "No available packages to scan. Try again later."


def test_entry_correctly_altered(api_url: str):
    r = requests.post(f"{api_url}/job")
    r.raise_for_status()

    r = requests.get(f"{api_url}/package?name=a&version=0.2.0")
    assert r.json()[0]["status"] == "pending"
