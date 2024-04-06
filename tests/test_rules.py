from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, Mock
from zipfile import ZipFile

from pytest import MonkeyPatch

from mainframe.endpoints.rules import get_rules
from mainframe.rules import (
    Rules,
    build_auth_header,
    fetch_commit_hash,
    fetch_rules,
    fetch_zipfile,
    parse_zipfile,
)


def test_build_auth_header():
    expected = {"Authorization": "Bearer token"}
    actual = build_auth_header("token")
    assert expected == actual


def test_fetch_commit_hash():
    mock_session: Any = Mock()
    url = "https://api.github.com/repos/owner-name/repo-name/commits/main"
    headers = {
        "Authorization": "Bearer token",
        "Accept": "application/vnd.github.sha",
    }

    attrs = {"return_value.text": "test commit hash"}
    mock_session.get = MagicMock(**attrs)  # pyright: ignore [reportArgumentType]
    commit_hash = fetch_commit_hash(mock_session, repository="owner-name/repo-name", access_token="token")
    mock_session.get.assert_called_once_with(url, headers=headers)
    assert commit_hash == "test commit hash"


def test_parse_zipfile():
    # Create a fake zipfile as returned by GitHub's API
    buffer = BytesIO()
    files = {
        "a.yara": "a",
        "b.yara": "b",
        "c.txt": "c",
    }

    expected = {
        "a": "a",
        "b": "b",
    }
    with ZipFile(buffer, "w") as zip:
        for filename, contents in files.items():
            zip.writestr(filename, contents)

        assert parse_zipfile(zip) == expected


def test_fetch_zipfile():
    mock_session: Any = Mock()
    url = "https://api.github.com/repos/owner-name/repo-name/zipball/"
    headers = {"Authorization": "Bearer token"}

    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip:
        zip.writestr("filename", "contents")

    attrs = {"return_value.content": buffer.getvalue()}
    mock_session.get = MagicMock(**attrs)  # pyright: ignore [reportArgumentType]
    zipfile = fetch_zipfile(mock_session, repository="owner-name/repo-name", access_token="token")
    mock_session.get.assert_called_once_with(url, headers=headers, follow_redirects=True)
    assert zipfile.namelist() == ["filename"]


def test_fetch_rules(monkeypatch: MonkeyPatch):
    files = {
        "file1": "some test contents of file1.yara",
        "file2": "more test contents of file2.yara",
    }

    buffer = BytesIO()
    zip = ZipFile(buffer, "w")
    for filename, contents in files.items():
        zip.writestr(filename + ".yara", contents)

    monkeypatch.setattr("mainframe.constants.mainframe_settings.dragonfly_github_token", "token")
    monkeypatch.setattr("mainframe.rules.fetch_commit_hash", Mock(return_value="test commit hash"))
    monkeypatch.setattr("mainframe.rules.fetch_zipfile", Mock(return_value=zip))

    mock_session: Any = Mock()
    expected = Rules(rules_commit="test commit hash", rules=files)
    actual = fetch_rules(mock_session)
    assert expected == actual

    zip.close()


def test_get_rules_endpoint():
    rules = Rules(rules_commit="test commit hash", rules={"file": "contents"})
    result = get_rules(rules)

    assert result.hash == rules.rules_commit
    assert result.rules == rules.rules
