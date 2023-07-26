from dataclasses import dataclass
from io import BytesIO
from typing import Final
from zipfile import ZipFile

from requests import Session

from mainframe.constants import mainframe_settings

REPO_ZIP_URL: Final[str] = "https://api.github.com/repos/vipyrsec/security-intelligence/zipball/"
REPO_TOP_COMMIT_URL: Final[str] = "https://api.github.com/repos/vipyrsec/security-intelligence/commits/main"
AUTH_HEADERS: Final[dict[str, str]] = {"Authorization": f"Bearer {mainframe_settings.dragonfly_github_token}"}
JSON_HEADERS: Final[dict[str, str]] = {"Accept": "application/vnd.github.VERSION.sha"}


@dataclass
class Rules:
    rules_commit: str
    rules: dict[str, str]


def fetch_rules(http_session: Session) -> Rules:
    """Return a dictionary mapping filenames to content"""

    # Running in a test environment, avoid hitting the GitHub API
    if mainframe_settings.dragonfly_github_token == "test":
        return Rules(rules_commit="test", rules={})

    rules = {}
    buffer = BytesIO()

    with http_session.get(REPO_ZIP_URL, headers=AUTH_HEADERS) as res:
        res.raise_for_status()
        bytes = res.content
        buffer.write(bytes)

    with http_session.get(REPO_TOP_COMMIT_URL, headers=JSON_HEADERS | AUTH_HEADERS) as res:
        bytes = res.content
        rules_commit = bytes.decode()

    buffer.seek(0)

    with ZipFile(buffer) as zip_file:
        for file_path in zip_file.namelist():
            if file_path.endswith(".yara"):
                file_name = file_path.split("/")[-1].removesuffix(".yara")

                rules[file_name] = zip_file.read(file_path).decode()

    return Rules(rules_commit=rules_commit, rules=rules)
