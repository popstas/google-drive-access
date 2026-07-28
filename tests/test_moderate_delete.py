import csv
import re
import sys

import pytest

from drive_audit.commands import parse_args
from drive_audit.commands.moderate_delete import (
    APPROVE_VALUES,
    REJECT_VALUES,
    apply,
    report,
    scan,
    watch,
)
from drive_audit.drive_activity import RenameEvent
from drive_audit.model import DriveConfig, ModerateDeleteConfig
from drive_audit.sheets_client import (
    DELETED_HEADERS,
    DELETED_HEADERS_V1,
    PENDING_HEADERS,
    PENDING_HEADERS_V1,
    PENDING_HEADERS_V2,
    SheetsClient,
)

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"


class Request:
    def __init__(self, callback):
        self.callback = callback

    def execute(self):
        return self.callback()


class FakeDriveFiles:
    def __init__(self, items):
        self.items = {item["id"]: dict(item) for item in items}
        self.list_calls = []
        self.update_calls = []
        self.fail_list_for = set()

    def get(self, fileId, **kwargs):
        def execute():
            if fileId not in self.items:
                raise RuntimeError(f"missing file {fileId}")
            return dict(self.items[fileId])

        return Request(execute)

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        match = re.search(r"'([^']+)' in parents", kwargs["q"])
        parent_id = match.group(1)

        def execute():
            if parent_id in self.fail_list_for:
                raise RuntimeError(f"list failed for {parent_id}")
            children = [
                dict(item)
                for item in self.items.values()
                if parent_id in (item.get("parents") or [])
                and not item.get("trashed", False)
            ]
            return {"files": children}

        return Request(execute)

    def update(self, fileId, body, **kwargs):
        self.update_calls.append((fileId, dict(body)))

        def execute():
            self.items[fileId].update(body)
            return {
                "id": fileId,
                "trashed": self.items[fileId].get("trashed", False),
            }

        return Request(execute)


class FakeDriveService:
    def __init__(self, items):
        self.resource = FakeDriveFiles(items)

    def files(self):
        return self.resource


class FakeValues:
    def __init__(self, service):
        self.service = service

    @staticmethod
    def _split_range(range_name):
        if "!" not in range_name:
            return range_name, None
        return tuple(range_name.split("!", 1))

    @staticmethod
    def _cell_coordinates(cell):
        match = re.fullmatch(r"([A-Z]+)(\d+)", cell)
        letters, row_text = match.groups()
        column = 0
        for letter in letters:
            column = column * 26 + (ord(letter) - ord("A") + 1)
        return int(row_text) - 1, column - 1

    def get(self, spreadsheetId, range):
        tab, _ = self._split_range(range)
        return Request(
            lambda: {"values": [list(row) for row in self.service.tabs.get(tab, [])]}
        )

    def clear(self, spreadsheetId, range, body):
        tab, _ = self._split_range(range)

        def execute():
            self.service.tabs[tab] = []
            return {}

        return Request(execute)

    def update(self, spreadsheetId, range, valueInputOption, body):
        tab, cell = self._split_range(range)

        def execute():
            if cell in (None, "A1"):
                self.service.tabs[tab] = [list(row) for row in body.get("values", [])]
                return {}
            row_index, column_index = self._cell_coordinates(cell)
            rows = self.service.tabs.setdefault(tab, [])
            while len(rows) <= row_index:
                rows.append([])
            while len(rows[row_index]) <= column_index:
                rows[row_index].append("")
            rows[row_index][column_index] = body["values"][0][0]
            return {}

        return Request(execute)

    def append(
        self,
        spreadsheetId,
        range,
        valueInputOption,
        insertDataOption,
        body,
    ):
        tab, _ = self._split_range(range)

        def execute():
            self.service.tabs.setdefault(tab, []).extend(
                [list(row) for row in body.get("values", [])]
            )
            return {}

        return Request(execute)

    def batchUpdate(self, spreadsheetId, body):
        def execute():
            for update in body.get("data", []):
                tab, cell = self._split_range(update["range"])
                row_index, column_index = self._cell_coordinates(cell)
                rows = self.service.tabs.setdefault(tab, [])
                while len(rows) <= row_index:
                    rows.append([])
                while len(rows[row_index]) <= column_index:
                    rows[row_index].append("")
                rows[row_index][column_index] = update["values"][0][0]
            return {}

        return Request(execute)


class FakeSpreadsheets:
    def __init__(self, tabs=None):
        self.tabs = tabs or {"Sheet1": []}
        self.values_resource = FakeValues(self)
        self.sheet_ids = {title: index + 100 for index, title in enumerate(self.tabs)}
        self.batch_requests = []

    def spreadsheets(self):
        return self

    def values(self):
        return self.values_resource

    def get(self, spreadsheetId):
        for title in self.tabs:
            self.sheet_ids.setdefault(title, max(self.sheet_ids.values()) + 1)
        return Request(
            lambda: {
                "sheets": [
                    {
                        "properties": {
                            "title": title,
                            "sheetId": self.sheet_ids[title],
                        }
                    }
                    for title in self.tabs
                ]
            }
        )

    def batchUpdate(self, spreadsheetId, body):
        def execute():
            for request in body.get("requests", []):
                self.batch_requests.append(request)
                if "addSheet" not in request:
                    continue
                title = request["addSheet"]["properties"]["title"]
                self.tabs.setdefault(title, [])
                self.sheet_ids.setdefault(title, max(self.sheet_ids.values()) + 1)
            return {}

        return Request(execute)


class FakeRenameResolver:
    def __init__(self, events):
        self.events = events
        self.calls = []
        self.clear_calls = 0

    def clear_activity_cache(self):
        self.clear_calls += 1

    def resolve_rename(self, file_id, current_name, marker, file_metadata=None):
        self.calls.append((file_id, current_name, marker, file_metadata))
        return self.events.get(file_id)


def item(
    file_id,
    name,
    parent=None,
    *,
    mime_type=DOC_MIME,
    trashed=False,
    can_trash=True,
    can_rename=True,
    drive_id=None,
):
    result = {
        "id": file_id,
        "name": name,
        "mimeType": mime_type,
        "parents": [parent] if parent else [],
        "createdTime": "2026-07-27T10:00:00Z",
        "modifiedTime": "2026-07-27T11:00:00Z",
        "trashed": trashed,
        "size": "123",
        "capabilities": {
            "canTrash": can_trash,
            "canRename": can_rename,
        },
    }
    if drive_id is not None:
        result["driveId"] = drive_id
    return result


def base_tree(extra=None):
    items = [
        item("root", "My Drive", mime_type=FOLDER_MIME),
        item("scope", "Target", "root", mime_type=FOLDER_MIME),
        item("outside", "Outside", "root", mime_type=FOLDER_MIME),
    ]
    items.extend(extra or [])
    return items


def drive_config(tmp_path, *, drive_id="", root_id="root"):
    return DriveConfig(
        credentials_file="credentials.json",
        delegated_user=None,
        drive_id=drive_id,
        root_folder_id=root_id,
        root_folder_name="My Drive",
        include_trashed=False,
        include_shortcuts=True,
        max_depth=None,
        limit=None,
        public_subdir=None,
        output_dir=str(tmp_path),
        yaml_file="audit.yml",
        files_csv="files.csv",
        permissions_csv="permissions.csv",
    )


def md_config(**overrides):
    values = {
        "sheet_id": "sheet-id",
        "name_marker": "+delete",
        "scan_roots": ["scope"],
        "scan_interval_seconds": 10,
        "max_per_run": 200,
        "report_csv": "deletions.csv",
        "use_activity_api": False,
        "allowed_renamer_domains": [],
        "allow_folder_delete": False,
    }
    values.update(overrides)
    return ModerateDeleteConfig(**values)


def sheets_client(tabs=None):
    service = FakeSpreadsheets(tabs)
    return service, SheetsClient(service, "sheet-id")


def pending_row(file_id, name, *, item_type="file", approve="yes", **overrides):
    row = {header: "" for header in PENDING_HEADERS}
    row.update(
        {
            "file_id": file_id,
            "item_type": item_type,
            "current_name": name,
            "path": f"/Target/{name}",
            "scan_root_id": "scope",
            "status": "pending",
            "approve": approve,
        }
    )
    row.update(overrides)
    return row


def seed_pending(service, rows):
    service.tabs["pending"] = [PENDING_HEADERS] + [
        [str(row.get(header, "")) for header in PENDING_HEADERS] for row in rows
    ]
    service.tabs["deleted"] = [DELETED_HEADERS]


def status_by_file(client):
    return {row["file_id"]: row["status"] for row in client.read_pending()}


def approval_by_file(client):
    return {row["file_id"]: row["approve"] for row in client.read_pending()}


def event(
    domain="example.com",
    *,
    actor="renamer@example.com",
    previous_name="old name",
):
    return RenameEvent(
        previous_name=previous_name,
        new_name="new +delete",
        renamed_at="2026-07-27T12:00:00Z",
        renamed_by=f"Renamer <{actor}>" if "@" in actor else actor,
        renamer_name="Renamer" if "@" in actor else actor,
        renamer_email=actor if "@" in actor else "",
        renamer_domain=domain,
        person_name="people/1",
    )


def test_scan_uses_names_only_and_stays_inside_selected_folder(tmp_path):
    drive = FakeDriveService(
        base_tree(
            [
                item("marked", "report +delete.docx", "scope"),
                item("appended", "report+delete", "scope"),
                item("plain", "report.docx", "scope"),
                item("longer-word", "report +deleted.docx", "scope"),
                item("embedded-word", "plus+deleteembedded.docx", "scope"),
                item("nested", "Nested", "scope", mime_type=FOLDER_MIME),
                item("deep", "+DELETE deep", "nested"),
                item(
                    "marked-folder",
                    "Archive +delete",
                    "scope",
                    mime_type=FOLDER_MIME,
                ),
                item("outside-marked", "outside +delete", "outside"),
            ]
        )
    )
    sheet_service, client = sheets_client()

    candidates = scan(drive, client, drive_config(tmp_path), md_config(), dry_run=False)

    assert {row["file_id"] for row in candidates} == {
        "marked",
        "appended",
        "deep",
        "marked-folder",
    }
    assert "outside-marked" not in {row["file_id"] for row in client.read_pending()}
    assert {row["item_type"] for row in candidates} == {"file", "folder"}
    assert any(row["path"] == "/Target/Nested/+DELETE deep" for row in candidates)
    assert {call["q"] for call in drive.resource.list_calls} == {
        "'scope' in parents and trashed = false",
        "'nested' in parents and trashed = false",
        "'marked-folder' in parents and trashed = false",
    }
    assert sheet_service.tabs["pending"][0] == PENDING_HEADERS


def test_scan_removes_marker_from_queue_and_reactivates_on_rename(tmp_path):
    drive = FakeDriveService(base_tree([item("file", "report +delete.docx", "scope")]))
    _, client = sheets_client()
    config = drive_config(tmp_path)
    moderate = md_config()

    scan(drive, client, config, moderate)
    rows = client.read_pending()
    assert len(rows) == 1
    client._service.tabs["pending"][1][PENDING_HEADERS.index("approve")] = "yes"

    drive.resource.items["file"]["name"] = "report.docx"
    scan(drive, client, config, moderate)
    assert status_by_file(client)["file"] == "marker_removed"
    assert approval_by_file(client)["file"] == ""

    drive.resource.items["file"]["name"] = "report +delete.docx"
    scan(drive, client, config, moderate)
    assert status_by_file(client)["file"] == "pending"
    assert approval_by_file(client)["file"] == ""
    assert len(client.read_pending()) == 1


def test_scan_marks_moved_item_out_of_scope(tmp_path):
    drive = FakeDriveService(base_tree([item("file", "report +delete.docx", "scope")]))
    _, client = sheets_client()
    scan(drive, client, drive_config(tmp_path), md_config())

    drive.resource.items["file"]["parents"] = ["outside"]
    scan(drive, client, drive_config(tmp_path), md_config())

    assert status_by_file(client)["file"] == "out_of_scope"


def test_scan_dry_run_does_not_create_or_update_tabs(tmp_path):
    drive = FakeDriveService(base_tree([item("file", "report +delete.docx", "scope")]))
    sheet_service, client = sheets_client()

    candidates = scan(drive, client, drive_config(tmp_path), md_config(), dry_run=True)

    assert len(candidates) == 1
    assert set(sheet_service.tabs) == {"Sheet1"}


def test_scan_fails_without_syncing_when_a_folder_listing_is_partial(tmp_path):
    drive = FakeDriveService(
        base_tree(
            [
                item("nested", "Nested", "scope", mime_type=FOLDER_MIME),
                item("file", "report +delete.docx", "nested"),
            ]
        )
    )
    drive.resource.fail_list_for.add("nested")
    sheet_service, client = sheets_client()

    with pytest.raises(RuntimeError, match="list failed"):
        scan(drive, client, drive_config(tmp_path), md_config())

    assert set(sheet_service.tabs) == {"Sheet1"}


def test_scan_records_rename_actor_and_enforces_domain(tmp_path):
    drive = FakeDriveService(
        base_tree(
            [
                item("allowed", "allowed +delete", "scope"),
                item("denied", "denied +delete", "scope"),
                item("unresolved", "unresolved +delete", "scope"),
            ]
        )
    )
    resolver = FakeRenameResolver(
        {
            "allowed": event("example.com"),
            "denied": event("other.test", actor="other@other.test"),
        }
    )
    _, client = sheets_client()

    candidates = scan(
        drive,
        client,
        drive_config(tmp_path),
        md_config(
            use_activity_api=True,
            allowed_renamer_domains=["EXAMPLE.COM"],
        ),
        dry_run=True,
        rename_resolver=resolver,
    )

    assert [row["file_id"] for row in candidates] == ["allowed"]
    assert candidates[0]["renamer_name"] == "Renamer"
    assert candidates[0]["renamer_email"] == "renamer@example.com"
    assert candidates[0]["renamed_at"] == "2026-07-27T12:00:00Z"
    assert resolver.clear_calls == 1


def test_scan_allows_every_domain_when_allowlist_is_empty(tmp_path):
    drive = FakeDriveService(base_tree([item("external", "external +delete", "scope")]))
    resolver = FakeRenameResolver(
        {"external": event("other.test", actor="external@other.test")}
    )
    _, client = sheets_client()

    candidates = scan(
        drive,
        client,
        drive_config(tmp_path),
        md_config(use_activity_api=True, allowed_renamer_domains=[]),
        dry_run=True,
        rename_resolver=resolver,
    )

    assert [row["file_id"] for row in candidates] == ["external"]


def test_domain_allowlist_normalizes_case_at_sign_and_trailing_dot(tmp_path):
    drive = FakeDriveService(base_tree([item("file", "file +delete", "scope")]))
    resolver = FakeRenameResolver({"file": event("example.com")})
    _, client = sheets_client()

    candidates = scan(
        drive,
        client,
        drive_config(tmp_path),
        md_config(
            use_activity_api=True,
            allowed_renamer_domains=[" @EXAMPLE.COM. "],
        ),
        dry_run=True,
        rename_resolver=resolver,
    )

    assert [row["file_id"] for row in candidates] == ["file"]


def test_strict_scan_blocks_an_existing_row_without_calling_it_marker_removed(
    tmp_path,
):
    drive = FakeDriveService(base_tree([item("file", "file +delete", "scope")]))
    _, client = sheets_client()
    config = drive_config(tmp_path)
    scan(drive, client, config, md_config())
    resolver = FakeRenameResolver(
        {"file": event("untrusted.test", actor="user@untrusted.test")}
    )

    scan(
        drive,
        client,
        config,
        md_config(
            use_activity_api=True,
            allowed_renamer_domains=["example.com"],
        ),
        rename_resolver=resolver,
    )

    assert status_by_file(client)["file"] == "renamer_not_allowed"


def test_watch_uses_configured_interval(tmp_path):
    drive = FakeDriveService(base_tree())
    _, client = sheets_client()
    sleeps = []

    cycles = watch(
        drive,
        client,
        drive_config(tmp_path),
        md_config(scan_interval_seconds=17),
        sleep_fn=sleeps.append,
        max_cycles=2,
    )

    assert cycles == 2
    assert sleeps == [17.0]


@pytest.mark.parametrize(
    "moderate",
    [
        md_config(name_marker=""),
        md_config(scan_interval_seconds=0),
        md_config(
            use_activity_api=True,
            allowed_renamer_domains=["person@example.com"],
        ),
        md_config(
            use_activity_api=False,
            allowed_renamer_domains=["example.com"],
        ),
    ],
)
def test_invalid_configuration_is_rejected(tmp_path, moderate):
    drive = FakeDriveService(base_tree())
    _, client = sheets_client()

    with pytest.raises(ValueError):
        scan(drive, client, drive_config(tmp_path), moderate, dry_run=True)


def test_cli_parser_accepts_watch(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "drive-audit",
            "--config",
            "data/config.yml",
            "moderate_delete",
            "watch",
            "--dry-run",
        ],
    )

    args = parse_args()

    assert args.command == "moderate_delete"
    assert args.action == "watch"
    assert args.dry_run is True


def test_apply_revalidates_marker_scope_trash_state_type_and_access(tmp_path):
    drive = FakeDriveService(
        base_tree(
            [
                item("eligible", "safe +delete", "scope"),
                item("outside-file", "outside +delete", "outside"),
                item("stale", "stale name", "scope"),
                item("already", "already +delete", "scope", trashed=True),
                item(
                    "folder",
                    "folder +delete",
                    "scope",
                    mime_type=FOLDER_MIME,
                ),
                item(
                    "no-access",
                    "locked +delete",
                    "scope",
                    can_trash=False,
                ),
            ]
        )
    )
    sheet_service, client = sheets_client()
    rows = [
        pending_row("eligible", "safe +delete"),
        pending_row("outside-file", "outside +delete"),
        pending_row("stale", "stale +delete"),
        pending_row("already", "already +delete"),
        pending_row("folder", "folder +delete", item_type="folder"),
        pending_row("no-access", "locked +delete"),
    ]
    seed_pending(sheet_service, rows)
    config = drive_config(tmp_path)
    moderate = md_config()

    preview = apply(drive, client, config, moderate, apply=False)
    assert [row["file_id"] for row in preview] == ["eligible"]
    assert drive.resource.update_calls == []
    assert all(row["status"] == "pending" for row in client.read_pending())

    deleted = apply(drive, client, config, moderate, apply=True)

    assert [row["file_id"] for row in deleted] == ["eligible"]
    assert drive.resource.items["eligible"]["trashed"] is True
    assert drive.resource.items["outside-file"]["trashed"] is False
    statuses = status_by_file(client)
    assert statuses == {
        "eligible": "trashed",
        "outside-file": "out_of_scope",
        "stale": "marker_removed",
        "already": "already_trashed",
        "folder": "folder_blocked",
        "no-access": "no_access",
    }
    assert all(value == "" for value in approval_by_file(client).values())
    assert len(client.read_deleted()) == 1


def test_apply_deduplicates_file_ids_and_honors_limit(tmp_path):
    files = [
        item("one", "one +delete", "scope"),
        item("two", "two +delete", "scope"),
        item("three", "three +delete", "scope"),
    ]
    drive = FakeDriveService(base_tree(files))
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service,
        [
            pending_row("one", "one +delete"),
            pending_row("one", "one +delete"),
            pending_row("two", "two +delete"),
            pending_row("three", "three +delete"),
        ],
    )

    deleted = apply(
        drive,
        client,
        drive_config(tmp_path),
        md_config(max_per_run=2),
        apply=True,
    )

    assert [row["file_id"] for row in deleted] == ["one", "two"]
    assert [call[0] for call in drive.resource.update_calls] == ["one", "two"]
    assert drive.resource.items["three"]["trashed"] is False


def test_apply_accepts_visible_and_hidden_approval_aliases(tmp_path):
    decisions = {
        "yes": "yes",
        "one": "1",
        "ru-yes": "да",
        "no": "no",
        "zero": "0",
        "ru-no": "нет",
    }
    drive = FakeDriveService(
        base_tree(
            [item(file_id, f"{file_id} +delete", "scope") for file_id in decisions]
        )
    )
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service,
        [
            pending_row(
                file_id,
                f"{file_id} +delete",
                approve=decision,
            )
            for file_id, decision in decisions.items()
        ],
    )

    preview = apply(
        drive,
        client,
        drive_config(tmp_path),
        md_config(),
        apply=False,
    )

    assert {row["file_id"] for row in preview} == {"yes", "one", "ru-yes"}
    assert all(row["status"] == "pending" for row in client.read_pending())
    assert drive.resource.update_calls == []

    deleted = apply(
        drive,
        client,
        drive_config(tmp_path),
        md_config(),
        apply=True,
    )

    assert {row["file_id"] for row in deleted} == {"yes", "one", "ru-yes"}
    assert status_by_file(client) == {
        "yes": "trashed",
        "one": "trashed",
        "ru-yes": "trashed",
        "no": "rejected",
        "zero": "rejected",
        "ru-no": "rejected",
    }
    assert all(value == "" for value in approval_by_file(client).values())
    assert drive.resource.items["no"]["name"] == "no"
    assert drive.resource.items["zero"]["name"] == "zero"
    assert drive.resource.items["ru-no"]["name"] == "ru-no"
    assert APPROVE_VALUES == {"yes", "1", "да"}
    assert REJECT_VALUES == {"no", "0", "нет"}


def test_rejection_restores_activity_previous_name_when_marker_is_entire_name(
    tmp_path,
):
    drive = FakeDriveService(base_tree([item("file", "+delete", "scope")]))
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service,
        [
            pending_row(
                "file",
                "+delete",
                approve="no",
                previous_name="Sheet fallback",
            )
        ],
    )
    resolver = FakeRenameResolver({"file": event(previous_name="Last non-empty name")})

    deleted = apply(
        drive,
        client,
        drive_config(tmp_path),
        md_config(use_activity_api=True),
        apply=True,
        rename_resolver=resolver,
    )

    row = client.read_pending()[0]
    assert deleted == []
    assert drive.resource.items["file"]["name"] == "Last non-empty name"
    assert row["current_name"] == "Last non-empty name"
    assert row["status"] == "rejected"
    assert row["approve"] == ""


def test_rejection_does_not_rename_without_drive_permission(tmp_path):
    drive = FakeDriveService(
        base_tree(
            [
                item(
                    "file",
                    "file +delete",
                    "scope",
                    can_rename=False,
                )
            ]
        )
    )
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service,
        [pending_row("file", "file +delete", approve="no")],
    )

    deleted = apply(
        drive,
        client,
        drive_config(tmp_path),
        md_config(),
        apply=True,
    )

    assert deleted == []
    assert drive.resource.items["file"]["name"] == "file +delete"
    assert drive.resource.update_calls == []
    assert status_by_file(client)["file"] == "no_access"


def test_rejection_wins_for_conflicting_duplicate_decisions(tmp_path):
    drive = FakeDriveService(base_tree([item("file", "file +delete", "scope")]))
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service,
        [
            pending_row("file", "file +delete", approve="yes"),
            pending_row("file", "file +delete", approve="no"),
        ],
    )

    deleted = apply(
        drive,
        client,
        drive_config(tmp_path),
        md_config(),
        apply=True,
    )

    assert deleted == []
    assert drive.resource.items["file"]["trashed"] is False
    assert drive.resource.items["file"]["name"] == "file"
    assert status_by_file(client)["file"] == "rejected"
    assert approval_by_file(client)["file"] == ""


def test_apply_can_delete_folder_only_when_explicitly_enabled(tmp_path):
    drive = FakeDriveService(
        base_tree(
            [
                item(
                    "folder",
                    "folder +delete",
                    "scope",
                    mime_type=FOLDER_MIME,
                )
            ]
        )
    )
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service,
        [pending_row("folder", "folder +delete", item_type="folder")],
    )

    deleted = apply(
        drive,
        client,
        drive_config(tmp_path),
        md_config(allow_folder_delete=True),
        apply=True,
    )

    assert [row["file_id"] for row in deleted] == ["folder"]
    assert drive.resource.items["folder"]["trashed"] is True


def test_apply_refuses_overlapping_folder_and_descendant_approvals(tmp_path):
    drive = FakeDriveService(
        base_tree(
            [
                item(
                    "folder",
                    "folder +delete",
                    "scope",
                    mime_type=FOLDER_MIME,
                ),
                item("child", "child +delete", "folder"),
            ]
        )
    )
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service,
        [
            pending_row("folder", "folder +delete", item_type="folder"),
            pending_row("child", "child +delete"),
        ],
    )

    deleted = apply(
        drive,
        client,
        drive_config(tmp_path),
        md_config(allow_folder_delete=True),
        apply=True,
    )

    assert deleted == []
    assert drive.resource.items["folder"]["trashed"] is False
    assert drive.resource.items["child"]["trashed"] is False
    assert status_by_file(client) == {
        "folder": "overlap_conflict",
        "child": "overlap_conflict",
    }


def test_apply_keeps_audit_when_pending_status_update_fails(tmp_path, monkeypatch):
    drive = FakeDriveService(base_tree([item("file", "file +delete", "scope")]))
    sheet_service, client = sheets_client()
    seed_pending(sheet_service, [pending_row("file", "file +delete")])

    def fail_status_update(*args, **kwargs):
        raise RuntimeError("status write failed")

    monkeypatch.setattr(client, "update_status", fail_status_update)

    deleted = apply(
        drive,
        client,
        drive_config(tmp_path),
        md_config(),
        apply=True,
    )

    assert [row["file_id"] for row in deleted] == ["file"]
    assert drive.resource.items["file"]["trashed"] is True
    assert client.read_deleted()[0]["file_id"] == "file"
    assert (tmp_path / "deletions.csv").exists()


def test_apply_rechecks_strict_renamer_domain(tmp_path):
    drive = FakeDriveService(base_tree([item("file", "file +delete", "scope")]))
    sheet_service, client = sheets_client()
    seed_pending(sheet_service, [pending_row("file", "file +delete")])
    resolver = FakeRenameResolver(
        {"file": event("untrusted.test", actor="user@untrusted.test")}
    )

    deleted = apply(
        drive,
        client,
        drive_config(tmp_path),
        md_config(
            use_activity_api=True,
            allowed_renamer_domains=["example.com"],
        ),
        apply=True,
        rename_resolver=resolver,
    )

    assert deleted == []
    assert drive.resource.items["file"]["trashed"] is False
    assert status_by_file(client)["file"] == "renamer_not_allowed"


def test_report_rebuilds_csv(tmp_path):
    sheet_service, client = sheets_client()
    deleted_row = {
        "deleted_at": "deleted",
        "approved_value": "yes",
        "previous_name": "old name",
        "current_name": "name +delete",
        "item_type": "file",
        "link": "https://drive.google.com/file/d/file/view",
        "renamer_name": "Renamer",
        "renamer_email": "renamer@example.com",
        "renamed_at": "renamed",
        "path": "/Target/name",
        "created_at": "created",
        "modified_at": "modified",
        "file_id": "file",
    }
    sheet_service.tabs["deleted"] = [
        DELETED_HEADERS,
        [deleted_row[header] for header in DELETED_HEADERS],
    ]
    sheet_service.tabs["pending"] = [PENDING_HEADERS]

    rows = report(client, drive_config(tmp_path), md_config())

    assert len(rows) == 1
    with (tmp_path / "deletions.csv").open(encoding="utf-8") as handle:
        written = list(csv.DictReader(handle))
    assert written[0]["file_id"] == "file"
    assert written[0]["renamer_name"] == "Renamer"
    assert written[0]["renamer_email"] == "renamer@example.com"


def test_ensure_tabs_rejects_old_or_custom_schema_without_overwriting_it():
    old_headers = [
        "file_id",
        "comment_id",
        "name",
        "status",
        "approve",
    ]
    service, client = sheets_client(
        {
            "pending": [
                old_headers,
                ["file", "comment", "name +delete", "pending", "yes"],
            ],
            "deleted": [DELETED_HEADERS],
        }
    )

    original = [list(row) for row in service.tabs["pending"]]

    with pytest.raises(ValueError, match="Unexpected pending header schema"):
        client.ensure_tabs()

    assert service.tabs["pending"] == original


def test_ensure_tabs_migrates_previous_queue_schema_and_preserves_approval():
    pending_values = {
        "file_id": "file",
        "item_type": "file",
        "name": "new +delete",
        "path": "/Target/new +delete",
        "scan_root_id": "scope",
        "created": "created",
        "modified": "modified",
        "size": "123",
        "renamed_by": "people/123",
        "renamer_domain": "",
        "renamed_at": "renamed",
        "previous_name": "old",
        "link": "https://drive.google.com/file/d/file/view",
        "status": "pending",
        "approve": "yes",
    }
    deleted_values = {
        "file_id": "deleted-file",
        "item_type": "file",
        "name": "deleted +delete",
        "path": "/Target/deleted +delete",
        "created": "created",
        "modified": "modified",
        "deleted_at": "deleted",
        "approved_value": "да",
        "renamed_by": "renamer@example.com",
        "renamed_at": "renamed",
    }
    service, client = sheets_client(
        {
            "pending": [
                PENDING_HEADERS_V1,
                [pending_values[header] for header in PENDING_HEADERS_V1],
            ],
            "deleted": [
                DELETED_HEADERS_V1,
                [deleted_values[header] for header in DELETED_HEADERS_V1],
            ],
        }
    )

    client.ensure_tabs()

    pending = client.read_pending()[0]
    deleted = client.read_deleted()[0]
    assert service.tabs["pending"][0] == PENDING_HEADERS
    assert pending["approve"] == "yes"
    assert pending["current_name"] == "new +delete"
    assert pending["renamer_person_id"] == "people/123"
    assert service.tabs["deleted"][0] == DELETED_HEADERS
    assert deleted["current_name"] == "deleted +delete"
    assert deleted["renamer_email"] == "renamer@example.com"
    validation = next(
        request["setDataValidation"]["rule"]
        for request in service.batch_requests
        if "setDataValidation" in request
    )
    assert validation["condition"]["values"] == [
        {"userEnteredValue": "yes"},
        {"userEnteredValue": "no"},
    ]
    assert validation["strict"] is False


def test_ensure_tabs_reorders_previous_moderator_schema_without_data_loss():
    row = {header: f"value-{header}" for header in PENDING_HEADERS_V2}
    row.update(
        {
            "approve": "no",
            "status": "pending",
            "previous_name": "before",
            "current_name": "after +delete",
            "file_id": "file",
        }
    )
    service, client = sheets_client(
        {
            "pending": [
                PENDING_HEADERS_V2,
                [row[header] for header in PENDING_HEADERS_V2],
            ],
            "deleted": [DELETED_HEADERS],
        }
    )

    client.ensure_tabs()

    migrated = client.read_pending()[0]
    assert service.tabs["pending"][0] == PENDING_HEADERS
    assert PENDING_HEADERS[:9] == [
        "approve",
        "status",
        "previous_name",
        "item_type",
        "link",
        "renamer_name",
        "renamer_email",
        "renamed_at",
        "current_name",
    ]
    assert migrated == row
