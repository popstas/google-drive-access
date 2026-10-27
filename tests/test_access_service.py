from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError

from drive_audit import access_service
from drive_audit.http_utils import LocalizedError
from drive_audit.model import DriveConfig


def _drive_config(public_subdir=None, drive_id="") -> DriveConfig:
    return DriveConfig(
        credentials_file="",
        delegated_user=None,
        drive_id=drive_id,
        root_folder_id="root",
        root_folder_name="Root",
        include_trashed=False,
        include_shortcuts=True,
        max_depth=None,
        limit=None,
        public_subdir=public_subdir,
        output_dir="",
        yaml_file="",
        files_csv="",
        permissions_csv="",
        list_folder_children_cache_timeout=3600,
    )


class _StubPlanfix:
    def __init__(self, tasks):
        self._tasks = tasks

    def get_child_tasks(self, task_id: int):
        return self._tasks

    def get_manager(self, assignee_id: str):
        return {"google_account": f"{assignee_id}@example.com"}


def test_grant_access_filters_existing_accounts(monkeypatch):
    added_accounts = []

    def fake_add_user_permission(service, folder_id, account, role):
        added_accounts.append(account)
        return {"id": f"perm-{account}"}

    monkeypatch.setattr(access_service, "add_user_permission", fake_add_user_permission)
    monkeypatch.setattr(
        access_service,
        "get_file_permissions",
        lambda *_, **__: [
            {"type": "user", "emailAddress": "200@example.com"},
        ],
    )
    monkeypatch.setattr(access_service, "ensure_public_subdir", lambda *_, **__: None)

    tasks = [{"assignees": {"users": [{"id": "user:200"}]}}]
    planfix_client = _StubPlanfix(tasks)
    drive_config = _drive_config()

    report = access_service.grant_access(
        planfix_client,
        drive_service=None,
        drive_config=drive_config,
        role="reader",
        task_id=1,
        initial_assignee_ids=["100"],
        folder_id="folder123",
    )

    assert added_accounts == ["100@example.com"]
    assert report["granted_accounts"] == ["100@example.com"]
    assert report["existing_accounts"] == ["200@example.com"]


def test_grant_access_with_email_list(monkeypatch):
    """grant_access should accept a list of emails and skip Planfix lookup."""
    added_accounts = []

    def fake_add_user_permission(service, folder_id, account, role):
        added_accounts.append(account)
        return {"id": f"perm-{account}"}

    monkeypatch.setattr(access_service, "add_user_permission", fake_add_user_permission)
    monkeypatch.setattr(
        access_service,
        "get_file_permissions",
        lambda *_, **__: [{"type": "user", "emailAddress": "already@example.com"}],
    )
    monkeypatch.setattr(access_service, "ensure_public_subdir", lambda *_, **__: None)

    def fail_get_child_tasks(*_args, **_kwargs):
        raise AssertionError("Planfix path should be skipped when email is given")

    planfix_client = type("PF", (), {"get_child_tasks": fail_get_child_tasks})()
    drive_config = _drive_config()

    report = access_service.grant_access(
        planfix_client,
        drive_service=None,
        drive_config=drive_config,
        role="reader",
        task_id=0,
        initial_assignee_ids=[],
        folder_id="folder123",
        email=["new@example.com", "already@example.com", "new@example.com"],
    )

    assert added_accounts == ["new@example.com"]
    assert report["granted_accounts"] == ["new@example.com"]
    assert report["existing_accounts"] == ["already@example.com"]


def test_grant_access_with_comma_separated_email_string(monkeypatch):
    """grant_access should split a comma-separated email string into a list."""
    added_accounts = []

    def fake_add_user_permission(service, folder_id, account, role):
        added_accounts.append(account)
        return {"id": f"perm-{account}"}

    monkeypatch.setattr(access_service, "add_user_permission", fake_add_user_permission)
    monkeypatch.setattr(
        access_service,
        "get_file_permissions",
        lambda *_, **__: [],
    )
    monkeypatch.setattr(access_service, "ensure_public_subdir", lambda *_, **__: None)

    planfix_client = type("PF", (), {})()
    drive_config = _drive_config()

    report = access_service.grant_access(
        planfix_client,
        drive_service=None,
        drive_config=drive_config,
        role="reader",
        task_id=0,
        initial_assignee_ids=[],
        folder_id="folder123",
        email="a@example.com, b@example.com, , a@example.com",
    )

    assert added_accounts == ["a@example.com", "b@example.com"]
    assert report["granted_accounts"] == ["a@example.com", "b@example.com"]
    assert report["existing_accounts"] == []


def _fail_on_change(monkeypatch):
    """Make any Drive write or Planfix lookup fail the test."""

    def boom(*_args, **_kwargs):
        raise AssertionError("nothing should be touched for this folder")

    monkeypatch.setattr(access_service, "add_user_permission", boom)
    monkeypatch.setattr(access_service, "get_file_permissions", boom)
    monkeypatch.setattr(access_service, "ensure_public_subdir", boom)
    return type("PF", (), {"get_child_tasks": boom})()


def test_grant_access_refuses_folder_outside_shared_drive(monkeypatch):
    """A folder in someone's My Drive cannot be managed by the service account."""
    planfix_client = _fail_on_change(monkeypatch)
    monkeypatch.setattr(
        access_service,
        "get_file_metadata",
        lambda *_: {"id": "folder123", "mimeType": "folder"},
    )

    with pytest.raises(LocalizedError) as exc_info:
        access_service.grant_access(
            planfix_client,
            drive_service=None,
            drive_config=_drive_config(public_subdir="public", drive_id="drive1"),
            role="reader",
            task_id=1,
            initial_assignee_ids=["100"],
            folder_id="folder123",
        )

    assert exc_info.value.key == "folder_outside_drive"


def test_grant_access_refuses_folder_on_another_shared_drive(monkeypatch):
    planfix_client = _fail_on_change(monkeypatch)
    monkeypatch.setattr(
        access_service,
        "get_file_metadata",
        lambda *_: {"id": "folder123", "driveId": "other-drive"},
    )

    with pytest.raises(LocalizedError) as exc_info:
        access_service.grant_access(
            planfix_client,
            drive_service=None,
            drive_config=_drive_config(drive_id="drive1"),
            role="reader",
            task_id=0,
            initial_assignee_ids=[],
            folder_id="folder123",
            email="a@example.com",
        )

    assert exc_info.value.key == "folder_outside_drive"


def test_grant_access_reports_missing_folder(monkeypatch):
    planfix_client = _fail_on_change(monkeypatch)

    def not_found(*_args):
        raise HttpError(
            resp=SimpleNamespace(status=404, reason="Not Found"), content=b""
        )

    monkeypatch.setattr(access_service, "get_file_metadata", not_found)

    with pytest.raises(LocalizedError) as exc_info:
        access_service.grant_access(
            planfix_client,
            drive_service=None,
            drive_config=_drive_config(drive_id="drive1"),
            role="reader",
            task_id=0,
            initial_assignee_ids=[],
            folder_id="folder123",
            email="a@example.com",
        )

    assert exc_info.value.key == "folder_not_found"


def test_grant_access_accepts_folder_on_configured_drive(monkeypatch):
    added_accounts = []
    monkeypatch.setattr(
        access_service,
        "get_file_metadata",
        lambda *_: {"id": "folder123", "driveId": "drive1"},
    )
    monkeypatch.setattr(
        access_service,
        "add_user_permission",
        lambda _s, _f, account, _r: added_accounts.append(account) or {"id": "p1"},
    )
    monkeypatch.setattr(access_service, "get_file_permissions", lambda *_, **__: [])
    monkeypatch.setattr(access_service, "ensure_public_subdir", lambda *_, **__: None)

    report = access_service.grant_access(
        type("PF", (), {})(),
        drive_service=None,
        drive_config=_drive_config(drive_id="drive1"),
        role="reader",
        task_id=0,
        initial_assignee_ids=[],
        folder_id="folder123",
        email="a@example.com",
    )

    assert added_accounts == ["a@example.com"]
    assert report["granted_accounts"] == ["a@example.com"]


def test_create_client_folder_handles_existing(monkeypatch):
    drive_config = _drive_config()
    monkeypatch.setattr(
        access_service, "find_child_folder", lambda *_, **__: {"id": "existing"}
    )

    folder, created = access_service.create_client_folder(
        None, drive_config, "Existing"
    )

    assert folder["id"] == "existing"
    assert created is False


def test_create_client_folder_creates_new_folder(monkeypatch):
    drive_config = _drive_config()
    monkeypatch.setattr(access_service, "find_child_folder", lambda *_, **__: None)
    monkeypatch.setattr(
        access_service, "create_folder", lambda *_, **__: {"id": "new-folder"}
    )

    folder, created = access_service.create_client_folder(None, drive_config, "New")

    assert folder["id"] == "new-folder"
    assert created is True


def test_create_client_folder_validates_name(monkeypatch):
    drive_config = _drive_config()
    monkeypatch.setattr(access_service, "find_child_folder", lambda *_, **__: None)

    for name in [" ", ""]:
        with pytest.raises(LocalizedError):
            access_service.create_client_folder(None, drive_config, name)


def test_get_task_and_assignees_reports_missing_task(monkeypatch):
    planfix_client = type("PF", (), {"get_client_task": lambda *_: {"found": False}})()

    with pytest.raises(LocalizedError):
        access_service.get_task_and_assignees(planfix_client, 10)
