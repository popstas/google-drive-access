"""Drive requests survive a keep-alive socket closed during idle.

A long-lived service object fails its first request after a pause with
BrokenPipeError. These tests drive the real googleapiclient request code
over a fake transport to check that such a request is retried.
"""

import json

import httplib2
import pytest
from googleapiclient.discovery import build

from drive_audit import access_service
from drive_audit.model import DriveConfig

DRIVE_ID = "drive-1"
FOLDER_ID = "folder-1"


class _FlakyHttp:
    """Raise BrokenPipeError on the first request, then answer by route."""

    def __init__(self, permissions):
        self.permissions = permissions
        self.calls = []
        self._failed = False

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        self.calls.append((method, uri.split("?")[0]))
        if not self._failed:
            self._failed = True
            raise BrokenPipeError(32, "Broken pipe")

        path = uri.split("?")[0]
        if method == "POST" and path.endswith("/permissions"):
            payload = json.loads(body)
            created = {"id": "perm-new", **payload}
            self.permissions.append(created)
            return self._ok(created)
        if method == "GET" and path.endswith("/permissions"):
            return self._ok({"permissions": list(self.permissions)})
        if method == "GET" and path.endswith(f"/files/{FOLDER_ID}"):
            return self._ok({"id": FOLDER_ID, "driveId": DRIVE_ID})
        raise AssertionError(f"unexpected request {method} {uri}")

    @staticmethod
    def _ok(data):
        return httplib2.Response({"status": "200"}), json.dumps(data).encode()


def _drive_config() -> DriveConfig:
    return DriveConfig(
        credentials_file="",
        delegated_user=None,
        drive_id=DRIVE_ID,
        root_folder_id="root",
        root_folder_name="Root",
        include_trashed=False,
        include_shortcuts=True,
        max_depth=None,
        limit=None,
        public_subdir=None,
        output_dir="",
        yaml_file="",
        files_csv="",
        permissions_csv="",
        list_folder_children_cache_timeout=3600,
    )


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setattr("googleapiclient.http.time.sleep", lambda seconds: None)


def _grant(http, email):
    service = build("drive", "v3", http=http, static_discovery=True)
    return access_service.grant_access(
        None, service, _drive_config(), "writer", 1, [], FOLDER_ID, email=email
    )


def _creates(http):
    return [call for call in http.calls if call[0] == "POST"]


def test_grant_access_retries_broken_pipe_and_grants_new_account():
    http = _FlakyHttp(permissions=[])

    result = _grant(http, "new@example.com")

    assert result == {"granted_accounts": ["new@example.com"], "existing_accounts": []}
    assert http.calls[0] == http.calls[1]  # the failed metadata get was repeated
    assert len(_creates(http)) == 1


def test_grant_access_retry_does_not_create_existing_permission():
    http = _FlakyHttp(
        permissions=[{"id": "p1", "type": "user", "emailAddress": "old@example.com"}]
    )

    result = _grant(http, "old@example.com")

    assert result == {"granted_accounts": [], "existing_accounts": ["old@example.com"]}
    assert _creates(http) == []
