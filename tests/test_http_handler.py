from types import SimpleNamespace

import pytest

from drive_audit.http import create_client_folder as create_client_folder_route
from drive_audit.http import create_handler
from drive_audit.http import set_client_folder_access as set_client_folder_access_route
from drive_audit.http_utils import LocalizedError
from drive_audit.model import DriveConfig, HttpConfig


class StubHandlerMixin:
    """Helper to mimic JsonRequestHandler for unit tests."""

    def __init__(self):
        self.responses = []
        self.path = "/"

    def send_json(self, status_code, payload):
        self.responses.append((status_code, payload))


@pytest.fixture
def drive_config():
    return DriveConfig(
        credentials_file="creds.json",
        delegated_user=None,
        drive_id="drive",
        root_folder_id="root",
        root_folder_name="Root",
        include_trashed=False,
        include_shortcuts=True,
        max_depth=None,
        limit=None,
        public_subdir=None,
        output_dir="./data",
        yaml_file="drive_audit.yml",
        files_csv="files.csv",
        permissions_csv="permissions.csv",
    )


@pytest.fixture
def http_config():
    return HttpConfig(port=0, token="secret", lang="en")


def build_handler(planfix_client, service, http_config, drive_config):
    handler_cls = create_handler(
        planfix_client, service, http_config, drive_config, "reader"
    )
    handler = handler_cls.__new__(handler_cls)
    StubHandlerMixin.__init__(handler)
    handler.send_json = StubHandlerMixin.send_json.__get__(handler)
    handler.headers = {}
    handler.rfile = None
    handler.requestline = ""
    return handler


def test_set_client_folder_access_missing_fields(
    monkeypatch, drive_config, http_config
):
    planfix_client = object()
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)

    handler.translate = lambda key, **context: f"translated:{key}:{context}"  # type: ignore

    set_client_folder_access_route.handle(
        handler,
        {"contact_id": 1},
        planfix_client=planfix_client,
        service=service,
        drive_config=drive_config,
        role="reader",
    )

    assert handler.responses[0][0] == 200
    assert handler.responses[0][1]["answer"].startswith("translated:missing_fields")


def test_create_client_folder_existing(monkeypatch, drive_config, http_config):
    planfix_client = SimpleNamespace(calls=[])
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)

    def fake_get_task_and_assignees(client, contact_id):
        client.calls.append(("task", contact_id))
        return 123, [1, 2]

    monkeypatch.setattr(
        "drive_audit.http.create_client_folder.get_task_and_assignees",
        fake_get_task_and_assignees,
    )
    monkeypatch.setattr(
        "drive_audit.http.create_client_folder.create_client_folder",
        lambda service, cfg, name: ({"id": "folder123"}, False),
    )

    monkeypatch.setattr(
        "drive_audit.http.create_client_folder.grant_access",
        lambda *args, **kwargs: {"granted_accounts": [], "existing_accounts": []},
    )

    handler.translate = lambda key, **context: f"translated:{key}:{context}"  # type: ignore

    create_client_folder_route.handle(
        handler,
        {"contact_id": 5, "folder_name": "Client"},
        planfix_client=planfix_client,
        service=service,
        drive_config=drive_config,
        role="reader",
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert payload["answer"].startswith("translated:client_folder_exists")


def test_set_client_folder_access_task_and_assignee(
    monkeypatch, drive_config, http_config
):
    planfix_client = SimpleNamespace()
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.extract_folder_id",
        lambda url: "folder-xyz",
    )

    def fake_normalize(ids):
        raise LocalizedError("client_task_not_found")

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.normalize_assignee_ids",
        fake_normalize,
    )

    handler.translate = lambda key, **context: f"translated:{key}:{context}"  # type: ignore

    set_client_folder_access_route.handle(
        handler,
        {
            "contact_id": 2,
            "folder_url": "http://example",
            "task_id": 1,
            "assignee_id": "1",
        },
        planfix_client=planfix_client,
        service=service,
        drive_config=drive_config,
        role="reader",
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert payload["answer"] == "translated:client_task_not_found:{}"
