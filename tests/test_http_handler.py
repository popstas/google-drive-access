from types import SimpleNamespace

import pytest

from drive_audit.access_service import extract_file_id
from drive_audit.http import create_client_folder as create_client_folder_route
from drive_audit.http import create_handler
from drive_audit.http import set_client_folder_access as set_client_folder_access_route
from drive_audit.http import share_folder as share_folder_route
from drive_audit.http import share_file as share_file_route
from drive_audit.http_utils import LocalizedError
from drive_audit.model import DriveConfig, HttpConfig, ShareFileConfig


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


# --- extract_file_id tests ---


class TestExtractFileId:
    def test_document_url(self):
        url = "https://docs.google.com/document/d/abc123_-X/edit"
        assert extract_file_id(url) == "abc123_-X"

    def test_spreadsheets_url(self):
        url = "https://docs.google.com/spreadsheets/d/sheet123/edit#gid=0"
        assert extract_file_id(url) == "sheet123"

    def test_presentation_url(self):
        url = "https://docs.google.com/presentation/d/pres456/edit"
        assert extract_file_id(url) == "pres456"

    def test_drive_file_url(self):
        url = "https://drive.google.com/file/d/file789/view"
        assert extract_file_id(url) == "file789"

    def test_drive_open_id(self):
        url = "https://drive.google.com/open?id=openID123"
        assert extract_file_id(url) == "openID123"

    def test_folders_url(self):
        url = "https://drive.google.com/drive/folders/folder999"
        assert extract_file_id(url) == "folder999"

    def test_invalid_url_raises(self):
        with pytest.raises(LocalizedError) as exc_info:
            extract_file_id("https://example.com/nothing")
        assert exc_info.value.key == "unable_extract_file_id"


# --- share_file route tests ---


@pytest.fixture
def share_file_config():
    return ShareFileConfig(days=90, role="commenter")


def _make_stub_handler(http_config, drive_config, share_file_config=None):
    planfix_client = object()
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)
    handler.translate = lambda key, **context: f"translated:{key}:{context}"  # type: ignore
    return handler, service


def test_share_file_missing_document_url(drive_config, http_config, share_file_config):
    handler, service = _make_stub_handler(http_config, drive_config)

    share_file_route.handle(
        handler,
        {},
        service=service,
        drive_config=drive_config,
        share_file_config=share_file_config,
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "missing_fields" in payload["answer"]


def test_share_file_not_found(monkeypatch, drive_config, http_config, share_file_config):
    handler, service = _make_stub_handler(http_config, drive_config)

    monkeypatch.setattr(
        "drive_audit.http.share_file.extract_file_id",
        lambda url: "file123",
    )

    resp = SimpleNamespace(status=404, reason="Not Found")

    def fake_get_metadata(svc, fid):
        raise __import__("googleapiclient.errors", fromlist=["HttpError"]).HttpError(
            resp, b"not found"
        )

    monkeypatch.setattr(
        "drive_audit.http.share_file.get_file_metadata",
        fake_get_metadata,
    )

    share_file_route.handle(
        handler,
        {"document_url": "https://docs.google.com/document/d/file123/edit"},
        service=service,
        drive_config=drive_config,
        share_file_config=share_file_config,
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "share_file_not_found" in payload["answer"]


def test_share_file_outside_drive(
    monkeypatch, drive_config, http_config, share_file_config
):
    handler, service = _make_stub_handler(http_config, drive_config)

    monkeypatch.setattr(
        "drive_audit.http.share_file.extract_file_id",
        lambda url: "file123",
    )
    monkeypatch.setattr(
        "drive_audit.http.share_file.get_file_metadata",
        lambda svc, fid: {"id": "file123", "name": "Test", "driveId": "other_drive"},
    )

    share_file_route.handle(
        handler,
        {"document_url": "https://docs.google.com/document/d/file123/edit"},
        service=service,
        drive_config=drive_config,
        share_file_config=share_file_config,
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "share_file_outside_drive" in payload["answer"]


def test_share_file_success_with_days(
    monkeypatch, drive_config, http_config, share_file_config
):
    handler, service = _make_stub_handler(http_config, drive_config)

    monkeypatch.setattr(
        "drive_audit.http.share_file.extract_file_id",
        lambda url: "file123",
    )
    monkeypatch.setattr(
        "drive_audit.http.share_file.get_file_metadata",
        lambda svc, fid: {"id": "file123", "name": "Test", "driveId": "drive"},
    )
    monkeypatch.setattr(
        "drive_audit.http.share_file.get_file_permissions",
        lambda svc, fid: [],
    )
    monkeypatch.setattr(
        "drive_audit.http.share_file.create_anyone_permission",
        lambda svc, fid, role, exp: {"id": "perm1"},
    )

    share_file_route.handle(
        handler,
        {"document_url": "https://docs.google.com/document/d/file123/edit"},
        service=service,
        drive_config=drive_config,
        share_file_config=share_file_config,
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "share_file_shared" in payload["answer"]
    assert "90" in payload["answer"]
    assert "commenter" in payload["answer"]


def test_share_file_success_no_expiration(
    monkeypatch, drive_config, http_config
):
    handler, service = _make_stub_handler(http_config, drive_config)
    config_no_expire = ShareFileConfig(days=0, role="reader")

    monkeypatch.setattr(
        "drive_audit.http.share_file.extract_file_id",
        lambda url: "file123",
    )
    monkeypatch.setattr(
        "drive_audit.http.share_file.get_file_metadata",
        lambda svc, fid: {"id": "file123", "name": "Test", "driveId": "drive"},
    )

    monkeypatch.setattr(
        "drive_audit.http.share_file.get_file_permissions",
        lambda svc, fid: [],
    )

    created_perms = []

    def fake_create(svc, fid, role, exp):
        created_perms.append({"role": role, "exp": exp})
        return {"id": "perm1"}

    monkeypatch.setattr(
        "drive_audit.http.share_file.create_anyone_permission",
        fake_create,
    )

    share_file_route.handle(
        handler,
        {"document_url": "https://docs.google.com/document/d/file123/edit"},
        service=service,
        drive_config=drive_config,
        share_file_config=config_no_expire,
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "share_file_shared_no_expire" in payload["answer"]
    assert created_perms[0]["exp"] is None


def test_share_file_already_shared(
    monkeypatch, drive_config, http_config, share_file_config
):
    handler, service = _make_stub_handler(http_config, drive_config)

    monkeypatch.setattr(
        "drive_audit.http.share_file.extract_file_id",
        lambda url: "file123",
    )
    monkeypatch.setattr(
        "drive_audit.http.share_file.get_file_metadata",
        lambda svc, fid: {"id": "file123", "name": "Test", "driveId": "drive"},
    )
    monkeypatch.setattr(
        "drive_audit.http.share_file.get_file_permissions",
        lambda svc, fid: [{"type": "anyone", "role": "reader"}],
    )

    share_file_route.handle(
        handler,
        {"document_url": "https://docs.google.com/document/d/file123/edit"},
        service=service,
        drive_config=drive_config,
        share_file_config=share_file_config,
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "share_file_already_shared" in payload["answer"]
    assert "reader" in payload["answer"]


# --- set_client_folder_access email tests ---


def test_set_client_folder_access_email_skips_planfix(
    monkeypatch, drive_config, http_config
):
    """When email is provided, grant_access is called with email kwarg and
    task/assignee Planfix logic is skipped entirely."""
    planfix_client = SimpleNamespace()
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)
    handler.translate = lambda key, **context: f"translated:{key}:{context}"

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.extract_folder_id",
        lambda url: "folder-abc",
    )

    grant_access_calls = []

    def fake_grant_access(*args, **kwargs):
        grant_access_calls.append((args, kwargs))
        return {"granted_accounts": ["user@example.com"], "existing_accounts": []}

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.grant_access",
        fake_grant_access,
    )

    # get_task_and_assignees should NOT be called
    def fail_get_task(*args, **kwargs):
        raise AssertionError("get_task_and_assignees should not be called")

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.get_task_and_assignees",
        fail_get_task,
    )

    set_client_folder_access_route.handle(
        handler,
        {
            "contact_id": 10,
            "folder_url": "https://drive.google.com/drive/folders/folder-abc",
            "email": "user@example.com",
        },
        planfix_client=planfix_client,
        service=service,
        drive_config=drive_config,
        role="reader",
    )

    assert len(grant_access_calls) == 1
    _, kwargs = grant_access_calls[0]
    assert kwargs["email"] == "user@example.com"

    status, payload = handler.responses[0]
    assert status == 200
    assert "granted_existing" in payload["answer"]


def test_set_client_folder_access_email_takes_precedence(
    monkeypatch, drive_config, http_config
):
    """When email is provided alongside task_id/assignee_id, email takes
    precedence and task/assignee logic is skipped."""
    planfix_client = SimpleNamespace()
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)
    handler.translate = lambda key, **context: f"translated:{key}:{context}"

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.extract_folder_id",
        lambda url: "folder-xyz",
    )

    grant_access_calls = []

    def fake_grant_access(*args, **kwargs):
        grant_access_calls.append((args, kwargs))
        return {"granted_accounts": ["boss@example.com"], "existing_accounts": []}

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.grant_access",
        fake_grant_access,
    )

    # normalize_assignee_ids should NOT be called when email is present
    def fail_normalize(*args, **kwargs):
        raise AssertionError("normalize_assignee_ids should not be called")

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.normalize_assignee_ids",
        fail_normalize,
    )

    set_client_folder_access_route.handle(
        handler,
        {
            "contact_id": 20,
            "folder_url": "https://drive.google.com/drive/folders/folder-xyz",
            "email": "boss@example.com",
            "task_id": 99,
            "assignee_id": "42",
        },
        planfix_client=planfix_client,
        service=service,
        drive_config=drive_config,
        role="writer",
    )

    assert len(grant_access_calls) == 1
    args, kwargs = grant_access_calls[0]
    assert kwargs["email"] == "boss@example.com"
    # task_id and initial_assignee_ids should be dummy values
    assert args[4] == 0  # task_id
    assert args[5] == []  # initial_assignee_ids

    status, payload = handler.responses[0]
    assert status == 200
    assert "granted_existing" in payload["answer"]


def test_set_client_folder_access_email_as_list(
    monkeypatch, drive_config, http_config
):
    """When email arrives as a list (e.g. ["user@example.com"]), it should be
    unwrapped to a plain string before being forwarded to grant_access."""
    planfix_client = SimpleNamespace()
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)
    handler.translate = lambda key, **context: f"translated:{key}:{context}"

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.extract_folder_id",
        lambda url: "folder-list",
    )

    grant_access_calls = []

    def fake_grant_access(*args, **kwargs):
        grant_access_calls.append((args, kwargs))
        return {"granted_accounts": ["user@example.com"], "existing_accounts": []}

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.grant_access",
        fake_grant_access,
    )

    set_client_folder_access_route.handle(
        handler,
        {
            "contact_id": 30,
            "folder_url": "https://drive.google.com/drive/folders/folder-list",
            "email": ["user@example.com"],
        },
        planfix_client=planfix_client,
        service=service,
        drive_config=drive_config,
        role="reader",
    )

    assert len(grant_access_calls) == 1
    _, kwargs = grant_access_calls[0]
    assert kwargs["email"] == "user@example.com"

    status, payload = handler.responses[0]
    assert status == 200
    assert "granted_existing" in payload["answer"]
    assert payload["folder_url"] == "https://drive.google.com/drive/folders/folder-list"


def test_set_client_folder_access_email_trailing_comma(
    monkeypatch, drive_config, http_config
):
    """Email with trailing comma should be stripped before calling grant_access."""
    planfix_client = SimpleNamespace()
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)
    handler.translate = lambda key, **context: f"translated:{key}:{context}"

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.extract_folder_id",
        lambda url: "folder-comma",
    )

    grant_access_calls = []

    def fake_grant_access(*args, **kwargs):
        grant_access_calls.append((args, kwargs))
        return {"granted_accounts": ["user@example.com"], "existing_accounts": []}

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.grant_access",
        fake_grant_access,
    )

    set_client_folder_access_route.handle(
        handler,
        {
            "contact_id": 30,
            "folder_url": "https://drive.google.com/drive/folders/folder-comma",
            "email": "user@example.com,",
        },
        planfix_client=planfix_client,
        service=service,
        drive_config=drive_config,
        role="reader",
    )

    assert len(grant_access_calls) == 1
    _, kwargs = grant_access_calls[0]
    assert kwargs["email"] == "user@example.com"

    status, payload = handler.responses[0]
    assert status == 200
    assert "granted_existing" in payload["answer"]


# --- lang override tests ---


def test_lang_override_in_payload(monkeypatch, drive_config, http_config):
    """When 'lang' is provided in the payload, handler.language is updated
    before the route handler runs."""
    planfix_client = SimpleNamespace()
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)

    assert handler.language == "en"

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.extract_folder_id",
        lambda url: "folder-lang",
    )
    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.get_task_and_assignees",
        lambda client, cid: (0, []),
    )
    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.grant_access",
        lambda *args, **kwargs: {"granted_accounts": [], "existing_accounts": []},
    )

    # Simulate do_POST lang extraction (list + uppercase like Planfix sends)
    payload = {
        "contact_id": 1,
        "folder_url": "https://drive.google.com/drive/folders/folder-lang",
        "lang": ["Ru"],
    }
    handler._apply_lang(payload)

    set_client_folder_access_route.handle(
        handler,
        payload,
        planfix_client=planfix_client,
        service=service,
        drive_config=drive_config,
        role="reader",
    )

    assert handler.language == "ru"
    status, payload_resp = handler.responses[0]
    assert status == 200
    # The translate method uses handler.language, so it should use Russian
    assert "Выданы права" in payload_resp["answer"]


def test_set_client_folder_access_public_permission(monkeypatch, drive_config, http_config):
    """When share_file_config is provided, create_anyone_permission is called after grant_access."""
    planfix_client = SimpleNamespace()
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)
    handler.translate = lambda key, **context: f"translated:{key}:{context}"

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.extract_folder_id",
        lambda url: "FOLDER123",
    )
    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.get_task_and_assignees",
        lambda client, cid: (0, []),
    )
    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.grant_access",
        lambda *args, **kwargs: {"granted_accounts": ["u@example.com"], "existing_accounts": []},
    )

    anyone_calls = []

    def fake_create_anyone(svc, file_id, role, expiration_time):
        anyone_calls.append((svc, file_id, role, expiration_time))

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.create_anyone_permission",
        fake_create_anyone,
    )

    share_cfg = ShareFileConfig(role="reader", days=7)
    set_client_folder_access_route.handle(
        handler,
        {"contact_id": 1, "folder_url": "https://drive.google.com/drive/folders/FOLDER123"},
        planfix_client=planfix_client,
        service=service,
        drive_config=drive_config,
        role="reader",
        share_file_config=share_cfg,
    )

    assert len(anyone_calls) == 1
    _, file_id, role, expiration_time = anyone_calls[0]
    assert file_id == "FOLDER123"
    assert role == "reader"
    assert expiration_time is not None  # days=7 so expiration should be set

    status, payload = handler.responses[0]
    assert status == 200
    assert "granted_existing" in payload["answer"]


def test_set_client_folder_access_public_permission_no_expiry(monkeypatch, drive_config, http_config):
    """When share_file_config.days == 0, expiration_time is None."""
    planfix_client = SimpleNamespace()
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)
    handler.translate = lambda key, **context: f"translated:{key}:{context}"

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.extract_folder_id",
        lambda url: "FOLDER456",
    )
    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.get_task_and_assignees",
        lambda client, cid: (0, []),
    )
    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.grant_access",
        lambda *args, **kwargs: {"granted_accounts": [], "existing_accounts": []},
    )

    anyone_calls = []

    def fake_create_anyone(svc, file_id, role, expiration_time):
        anyone_calls.append((svc, file_id, role, expiration_time))

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.create_anyone_permission",
        fake_create_anyone,
    )

    share_cfg = ShareFileConfig(role="reader", days=0)
    set_client_folder_access_route.handle(
        handler,
        {"contact_id": 1, "folder_url": "https://drive.google.com/drive/folders/FOLDER456"},
        planfix_client=planfix_client,
        service=service,
        drive_config=drive_config,
        role="reader",
        share_file_config=share_cfg,
    )

    assert len(anyone_calls) == 1
    _, file_id, role, expiration_time = anyone_calls[0]
    assert file_id == "FOLDER456"
    assert expiration_time is None


def test_set_client_folder_access_no_public_permission_without_config(
    monkeypatch, drive_config, http_config
):
    """When share_file_config is None, create_anyone_permission is not called."""
    planfix_client = SimpleNamespace()
    service = object()
    handler = build_handler(planfix_client, service, http_config, drive_config)
    handler.translate = lambda key, **context: f"translated:{key}:{context}"

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.extract_folder_id",
        lambda url: "FOLDER789",
    )
    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.get_task_and_assignees",
        lambda client, cid: (0, []),
    )
    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.grant_access",
        lambda *args, **kwargs: {"granted_accounts": [], "existing_accounts": []},
    )

    anyone_calls = []

    monkeypatch.setattr(
        "drive_audit.http.set_client_folder_access.create_anyone_permission",
        lambda *args: anyone_calls.append(args),
    )

    set_client_folder_access_route.handle(
        handler,
        {"contact_id": 1, "folder_url": "https://drive.google.com/drive/folders/FOLDER789"},
        planfix_client=planfix_client,
        service=service,
        drive_config=drive_config,
        role="reader",
        share_file_config=None,
    )

    assert len(anyone_calls) == 0


# --- share_folder tests ---


def _make_share_folder_handler(drive_config, http_config, writer_subdir=None):
    import dataclasses

    cfg = dataclasses.replace(drive_config, writer_subdir=writer_subdir)
    planfix_client = SimpleNamespace()
    service = object()
    handler = build_handler(planfix_client, service, http_config, cfg)
    handler.translate = lambda key, **context: f"translated:{key}:{context}"
    return handler, planfix_client, service, cfg


def test_share_folder_missing_fields(drive_config, http_config):
    handler, planfix_client, service, cfg = _make_share_folder_handler(
        drive_config, http_config, writer_subdir="docs"
    )

    share_folder_route.handle(
        handler,
        {"contact_id": 1},
        planfix_client=planfix_client,
        service=service,
        drive_config=cfg,
        role="writer",
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "missing_fields" in payload["answer"]


def test_share_folder_not_configured(drive_config, http_config):
    handler, planfix_client, service, cfg = _make_share_folder_handler(
        drive_config, http_config, writer_subdir=None
    )

    share_folder_route.handle(
        handler,
        {"contact_id": 1, "folder_url": "https://drive.google.com/drive/folders/PARENT"},
        planfix_client=planfix_client,
        service=service,
        drive_config=cfg,
        role="writer",
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "writer_subdir_not_configured" in payload["answer"]


def test_share_folder_subfolder_not_found(monkeypatch, drive_config, http_config):
    handler, planfix_client, service, cfg = _make_share_folder_handler(
        drive_config, http_config, writer_subdir="docs"
    )

    monkeypatch.setattr(
        "drive_audit.http.share_folder.extract_folder_id",
        lambda url: "PARENT",
    )
    monkeypatch.setattr(
        "drive_audit.http.share_folder.get_task_and_assignees",
        lambda client, cid: (0, []),
    )
    monkeypatch.setattr(
        "drive_audit.http.share_folder.find_child_folder",
        lambda svc, parent, name, drive: None,
    )

    share_folder_route.handle(
        handler,
        {"contact_id": 1, "folder_url": "https://drive.google.com/drive/folders/PARENT"},
        planfix_client=planfix_client,
        service=service,
        drive_config=cfg,
        role="writer",
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "subfolder_not_found" in payload["answer"]


def test_share_folder_not_a_folder(monkeypatch, drive_config, http_config):
    handler, planfix_client, service, cfg = _make_share_folder_handler(
        drive_config, http_config, writer_subdir="docs"
    )

    monkeypatch.setattr(
        "drive_audit.http.share_folder.extract_folder_id",
        lambda url: "PARENT",
    )
    monkeypatch.setattr(
        "drive_audit.http.share_folder.get_task_and_assignees",
        lambda client, cid: (0, []),
    )
    monkeypatch.setattr(
        "drive_audit.http.share_folder.find_child_folder",
        lambda svc, parent, name, drive: {"id": "SUB123", "name": "docs"},
    )
    monkeypatch.setattr(
        "drive_audit.http.share_folder.get_item_info",
        lambda svc, item_id: {
            "id": item_id,
            "name": "docs",
            "mimeType": "application/vnd.google-apps.document",
            "parents": ["PARENT"],
        },
    )

    share_folder_route.handle(
        handler,
        {"contact_id": 1, "folder_url": "https://drive.google.com/drive/folders/PARENT"},
        planfix_client=planfix_client,
        service=service,
        drive_config=cfg,
        role="writer",
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "subfolder_not_a_folder" in payload["answer"]


def test_share_folder_not_child(monkeypatch, drive_config, http_config):
    handler, planfix_client, service, cfg = _make_share_folder_handler(
        drive_config, http_config, writer_subdir="docs"
    )

    monkeypatch.setattr(
        "drive_audit.http.share_folder.extract_folder_id",
        lambda url: "PARENT",
    )
    monkeypatch.setattr(
        "drive_audit.http.share_folder.get_task_and_assignees",
        lambda client, cid: (0, []),
    )
    monkeypatch.setattr(
        "drive_audit.http.share_folder.find_child_folder",
        lambda svc, parent, name, drive: {"id": "SUB123", "name": "docs"},
    )
    monkeypatch.setattr(
        "drive_audit.http.share_folder.get_item_info",
        lambda svc, item_id: {
            "id": item_id,
            "name": "docs",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["OTHER_PARENT"],
        },
    )

    share_folder_route.handle(
        handler,
        {"contact_id": 1, "folder_url": "https://drive.google.com/drive/folders/PARENT"},
        planfix_client=planfix_client,
        service=service,
        drive_config=cfg,
        role="writer",
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "subfolder_not_child" in payload["answer"]


def test_share_folder_success(monkeypatch, drive_config, http_config):
    handler, planfix_client, service, cfg = _make_share_folder_handler(
        drive_config, http_config, writer_subdir="docs"
    )

    monkeypatch.setattr(
        "drive_audit.http.share_folder.extract_folder_id",
        lambda url: "PARENT",
    )
    monkeypatch.setattr(
        "drive_audit.http.share_folder.get_task_and_assignees",
        lambda client, cid: (42, [1, 2]),
    )
    monkeypatch.setattr(
        "drive_audit.http.share_folder.find_child_folder",
        lambda svc, parent, name, drive: {"id": "SUB123", "name": "docs"},
    )
    monkeypatch.setattr(
        "drive_audit.http.share_folder.get_item_info",
        lambda svc, item_id: {
            "id": item_id,
            "name": "docs",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["PARENT"],
        },
    )

    grant_calls = []

    def fake_grant_access(*args, **kwargs):
        grant_calls.append((args, kwargs))
        return {"granted_accounts": ["user@example.com"], "existing_accounts": []}

    monkeypatch.setattr(
        "drive_audit.http.share_folder.grant_access",
        fake_grant_access,
    )

    share_folder_route.handle(
        handler,
        {"contact_id": 1, "folder_url": "https://drive.google.com/drive/folders/PARENT"},
        planfix_client=planfix_client,
        service=service,
        drive_config=cfg,
        role="writer",
    )

    status, payload = handler.responses[0]
    assert status == 200
    assert "granted_existing" in payload["answer"]
    assert payload["folder_url"] == "https://drive.google.com/drive/folders/SUB123"
    assert payload["granted_accounts"] == ["user@example.com"]
    assert payload["existing_accounts"] == []

    # grant_access must be called with public_subdir=None to skip nested public dir
    _, kwargs = grant_calls[0]
    assert kwargs.get("folder_id") == "SUB123" or grant_calls[0][0][6] == "SUB123"
    # The drive_config passed to grant_access must have public_subdir=None
    passed_cfg = grant_calls[0][0][2]
    assert passed_cfg.public_subdir is None
