from dataclasses import dataclass
from io import BytesIO
from typing import Final
from zipfile import ZipFile

import httpx

from mainframe.constants import mainframe_settings

REPOSITORY: Final[str] = "vipyrsec/security-intelligence"


@dataclass
class Rules:
    rules_commit: str
    rules: dict[str, str]


def build_auth_header(access_token: str) -> dict[str, str]:
    """Build authentication headers given the access token"""
    return {"Authorization": f"Bearer {access_token}"}


def fetch_commit_hash(http_client: httpx.Client, *, repository: str, access_token: str) -> str:
    """Fetch the top commit hash of the given repository"""
    url = f"https://api.github.com/repos/{repository}/commits/main"
    authentication_headers = build_auth_header(access_token)
    json_headers = {"Accept": "application/vnd.github.sha"}
    headers = authentication_headers | json_headers
    return http_client.get(url, headers=headers).text


def parse_zipfile(zipfile: ZipFile) -> dict[str, str]:
    """Parse a zipfile and return a dict mapping filenames to content"""
    rules: dict[str, str] = {}

    for file_path in zipfile.namelist():
        if not file_path.endswith(".yara"):
            continue

        file_name = file_path.split("/")[-1].removesuffix(".yara")
        rules[file_name] = zipfile.read(file_path).decode()

    return rules


def fetch_zipfile(http_client: httpx.Client, *, repository: str, access_token: str) -> ZipFile:
    """Download the source zipfile from GitHub for the given repository"""
    url = f"https://api.github.com/repos/{repository}/zipball/"
    headers = build_auth_header(access_token)
    buffer = BytesIO()
    res = http_client.get(url, headers=headers, follow_redirects=True)
    res.raise_for_status()
    bytes = res.content
    buffer.write(bytes)

    return ZipFile(buffer)


def fetch_rules(http_client: httpx.Client) -> Rules:
    """Return the commit hash and all the rules"""

    access_token = mainframe_settings.dragonfly_github_token

    commit_hash = fetch_commit_hash(http_client, repository=REPOSITORY, access_token=access_token)

    zipfile = fetch_zipfile(http_client, repository=REPOSITORY, access_token=access_token)
    rules = parse_zipfile(zipfile)

    return Rules(rules_commit=commit_hash, rules=rules)
