"""Safety-focused tests for moderated deletion.

Green tests pin down behavior that keeps deletion reversible, scoped and
explicitly approved. ``xfail(strict=True)`` tests document known defects found
in review; they start failing (and must be un-marked) once the defect is fixed.
"""

import csv
import os
import sys

import pytest
from test_moderate_delete import (
    FOLDER_MIME,
    FakeDriveFiles,
    FakeDriveService,
    approval_by_file,
    base_tree,
    drive_config,
    item,
    md_config,
    pending_row,
    seed_pending,
    sheets_client,
    status_by_file,
)

from drive_audit.commands import moderate_delete as moderate_delete_module
from drive_audit.commands import parse_args
from drive_audit.commands.moderate_delete import (
    _has_marker,
    _remove_marker,
    _validate_config,
    apply,
    run_moderate_delete,
    scan,
)
from drive_audit.config_loader import build_moderate_delete_config


class FailingTrashFiles(FakeDriveFiles):
    def __init__(self, items, fail_ids):
        super().__init__(items)
        self.fail_ids = set(fail_ids)

    def update(self, fileId, body, **kwargs):
        if fileId in self.fail_ids and body.get("trashed"):
            self.update_calls.append((fileId, dict(body)))

            class Failing:
                def execute(self):
                    raise RuntimeError("trash refused")

            return Failing()
        return super().update(fileId, body, **kwargs)


def _csv_file_ids(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [row["file_id"] for row in csv.DictReader(handle)]


# --- green: dry-run default, trash-only, fail-closed checks ---------------


def test_cli_apply_without_flag_changes_nothing(tmp_path, monkeypatch):
    drive = FakeDriveService(base_tree([item("eligible", "safe +delete", "scope")]))
    sheet_service, _ = sheets_client()
    seed_pending(sheet_service, [pending_row("eligible", "safe +delete")])
    tabs_before = {
        tab: [list(r) for r in rows] for tab, rows in sheet_service.tabs.items()
    }
    monkeypatch.setattr(
        moderate_delete_module, "get_sheets_service", lambda config: sheet_service
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["drive-audit", "--config", "x.yml", "moderate_delete", "apply"],
    )
    args = parse_args()
    assert args.apply is False

    config_data = {
        "commands": {
            "moderate_delete": {
                "sheet_id": "sheet-id",
                "scan_roots": ["scope"],
                "report_csv": "deletions.csv",
            }
        }
    }
    run_moderate_delete(args, config_data, drive_config(tmp_path), drive)

    assert drive.resource.update_calls == []
    assert sheet_service.tabs == tabs_before
    assert not os.path.exists(tmp_path / "deletions.csv")


def test_apply_only_moves_to_trash_and_never_deletes(tmp_path):
    drive = FakeDriveService(base_tree([item("eligible", "safe +delete", "scope")]))
    # FakeDriveFiles has no delete(): a permanent delete would raise here.
    assert not hasattr(drive.resource, "delete")
    sheet_service, client = sheets_client()
    seed_pending(sheet_service, [pending_row("eligible", "safe +delete")])

    apply(drive, client, drive_config(tmp_path), md_config(), apply=True)

    assert drive.resource.update_calls == [("eligible", {"trashed": True})]


@pytest.mark.parametrize(
    "status, approve",
    [
        ("marker_removed", "yes"),
        ("error", "yes"),
        ("trashed", "yes"),
        ("", "yes"),
        ("pending", "y"),
        ("pending", "true"),
        ("pending", "yes!"),
        ("pending", "ok"),
        ("pending", "+"),
        ("pending", ""),
    ],
)
def test_apply_ignores_rows_that_are_not_pending_and_explicitly_approved(
    tmp_path, status, approve
):
    drive = FakeDriveService(base_tree([item("file", "file +delete", "scope")]))
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service,
        [pending_row("file", "file +delete", status=status, approve=approve)],
    )

    apply(drive, client, drive_config(tmp_path), md_config(), apply=True)

    assert drive.resource.update_calls == []
    assert drive.resource.items["file"]["trashed"] is False


def test_apply_never_trashes_the_scan_root_itself(tmp_path):
    items = base_tree()
    for entry in items:
        if entry["id"] == "scope":
            entry["name"] = "Target +delete"
    drive = FakeDriveService(items)
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service,
        [pending_row("scope", "Target +delete", item_type="folder")],
    )

    apply(
        drive,
        client,
        drive_config(tmp_path),
        md_config(allow_folder_delete=True),
        apply=True,
    )

    assert drive.resource.update_calls == []
    assert status_by_file(client)["scope"] == "out_of_scope"


def test_apply_fails_closed_when_ancestor_lookup_fails(tmp_path):
    drive = FakeDriveService(base_tree([item("orphan", "orphan +delete", "ghost")]))
    sheet_service, client = sheets_client()
    seed_pending(sheet_service, [pending_row("orphan", "orphan +delete")])

    apply(drive, client, drive_config(tmp_path), md_config(), apply=True)

    assert drive.resource.update_calls == []
    assert status_by_file(client)["orphan"] == "out_of_scope"


def test_apply_refuses_item_from_another_shared_drive(tmp_path):
    drive = FakeDriveService(
        base_tree([item("foreign", "foreign +delete", "scope", drive_id="other")])
    )
    sheet_service, client = sheets_client()
    seed_pending(sheet_service, [pending_row("foreign", "foreign +delete")])

    apply(
        drive,
        client,
        drive_config(tmp_path, drive_id="drive-1"),
        md_config(),
        apply=True,
    )

    assert drive.resource.update_calls == []
    assert status_by_file(client)["foreign"] == "out_of_scope"


def test_trash_failure_marks_error_and_continues_with_other_rows(tmp_path):
    items = base_tree(
        [
            item("broken", "broken +delete", "scope"),
            item("fine", "fine +delete", "scope"),
        ]
    )
    drive = FakeDriveService([])
    drive.resource = FailingTrashFiles(items, fail_ids={"broken"})
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service,
        [pending_row("broken", "broken +delete"), pending_row("fine", "fine +delete")],
    )

    deleted = apply(drive, client, drive_config(tmp_path), md_config(), apply=True)

    assert [row["file_id"] for row in deleted] == ["fine"]
    assert drive.resource.items["broken"]["trashed"] is False
    assert drive.resource.items["fine"]["trashed"] is True
    assert status_by_file(client) == {"broken": "error", "fine": "trashed"}
    assert [row["file_id"] for row in client.read_deleted()] == ["fine"]


def test_rejection_preview_does_not_rename(tmp_path):
    drive = FakeDriveService(base_tree([item("file", "report +delete.docx", "scope")]))
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service, [pending_row("file", "report +delete.docx", approve="no")]
    )

    apply(drive, client, drive_config(tmp_path), md_config(), apply=False)

    assert drive.resource.update_calls == []
    assert drive.resource.items["file"]["name"] == "report +delete.docx"
    assert status_by_file(client)["file"] == "pending"
    assert approval_by_file(client)["file"] == "no"


def test_watch_and_scan_never_mutate_drive(tmp_path):
    drive = FakeDriveService(
        base_tree(
            [
                item("file", "report +delete.docx", "scope"),
                item("folder", "Archive +delete", "scope", mime_type=FOLDER_MIME),
            ]
        )
    )
    _, client = sheets_client()

    scan(drive, client, drive_config(tmp_path), md_config(allow_folder_delete=True))

    assert drive.resource.update_calls == []


# --- xfail: defects found in review ---------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Straße +delete.docx", "Straße.docx"),
        ("ﬁle +delete.pdf", "ﬁle.pdf"),
        ("İstanbul +delete.txt", "İstanbul.txt"),
    ],
)
def test_remove_marker_keeps_names_whose_casefold_changes_length(name, expected):
    assert _remove_marker(name, "+delete") == expected


def test_rejection_rename_does_not_corrupt_extension(tmp_path):
    drive = FakeDriveService(base_tree([item("file", "Straße +delete.docx", "scope")]))
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service, [pending_row("file", "Straße +delete.docx", approve="no")]
    )

    apply(drive, client, drive_config(tmp_path), md_config(), apply=True)

    assert drive.resource.items["file"]["name"] == "Straße.docx"


@pytest.mark.xfail(
    strict=True,
    reason="audit rows are written after the loop; an exception mid-run loses them",
)
def test_audit_survives_status_update_failure_after_a_trash(tmp_path, monkeypatch):
    drive = FakeDriveService(
        base_tree(
            [
                item("first", "first +delete", "scope"),
                item("second", "second without marker", "scope"),
            ]
        )
    )
    sheet_service, client = sheets_client()
    seed_pending(
        sheet_service,
        [
            pending_row("first", "first +delete"),
            pending_row("second", "second +delete"),
        ],
    )
    original_update = client.update_status

    def flaky_update(file_id, status, **kwargs):
        if file_id == "second":
            raise RuntimeError("Sheets quota exceeded")
        return original_update(file_id, status, **kwargs)

    monkeypatch.setattr(client, "update_status", flaky_update)

    with pytest.raises(RuntimeError):
        apply(drive, client, drive_config(tmp_path), md_config(), apply=True)

    assert drive.resource.items["first"]["trashed"] is True
    csv_ids = _csv_file_ids(tmp_path / "deletions.csv")
    sheet_ids = [row["file_id"] for row in client.read_deleted()]
    assert "first" in csv_ids or "first" in sheet_ids


@pytest.mark.xfail(
    strict=True,
    reason="report CSV is overwritten by each apply run",
)
def test_csv_audit_is_not_overwritten_when_sheet_append_failed(tmp_path, monkeypatch):
    drive = FakeDriveService(
        base_tree(
            [
                item("first", "first +delete", "scope"),
                item("second", "second +delete", "scope"),
            ]
        )
    )
    sheet_service, client = sheets_client()
    config = drive_config(tmp_path)
    moderate = md_config()

    seed_pending(sheet_service, [pending_row("first", "first +delete")])
    original_append = client.append_deleted

    def failing_append(*args, **kwargs):
        raise RuntimeError("Sheets unavailable")

    monkeypatch.setattr(client, "append_deleted", failing_append)
    with pytest.raises(RuntimeError):
        apply(drive, client, config, moderate, apply=True)
    assert _csv_file_ids(tmp_path / "deletions.csv") == ["first"]

    monkeypatch.setattr(client, "append_deleted", original_append)
    seed_pending(sheet_service, [pending_row("second", "second +delete")])
    apply(drive, client, config, moderate, apply=True)

    assert "first" in _csv_file_ids(tmp_path / "deletions.csv")


@pytest.mark.xfail(
    strict=True,
    reason="approval is keyed by file_id only, not by the name the moderator saw",
)
def test_apply_refuses_when_live_name_differs_from_approved_row(tmp_path):
    drive = FakeDriveService(base_tree([item("file", "contract +delete", "scope")]))
    sheet_service, client = sheets_client()
    seed_pending(sheet_service, [pending_row("file", "draft +delete")])

    apply(drive, client, drive_config(tmp_path), md_config(), apply=True)

    assert drive.resource.items["file"]["trashed"] is False


@pytest.mark.xfail(
    strict=True,
    reason="scan keeps an existing approval after the item is renamed",
)
def test_scan_clears_approval_when_name_changes_after_approval(tmp_path):
    drive = FakeDriveService(base_tree([item("file", "contract +delete", "scope")]))
    sheet_service, client = sheets_client()
    seed_pending(sheet_service, [pending_row("file", "draft +delete")])

    scan(drive, client, drive_config(tmp_path), md_config())

    assert approval_by_file(client)["file"] == ""


@pytest.mark.xfail(strict=True, reason="only an empty marker is rejected")
@pytest.mark.parametrize("marker", [" ", "  ", "1", "a"])
def test_too_broad_marker_is_rejected(marker):
    with pytest.raises(ValueError):
        _validate_config(md_config(name_marker=marker))


def test_whitespace_marker_would_match_ordinary_names():
    # Documents the blast radius of the missing validation above.
    assert _has_marker("report (1).docx", " ") is True


@pytest.mark.xfail(strict=True, reason="name_marker: null becomes the string 'None'")
def test_null_marker_in_config_is_rejected():
    config = build_moderate_delete_config(
        {"commands": {"moderate_delete": {"sheet_id": "s", "name_marker": None}}}
    )
    with pytest.raises(ValueError):
        _validate_config(config)


@pytest.mark.xfail(
    strict=True,
    reason="marker has a right word boundary but no left one",
)
def test_word_marker_does_not_match_inside_a_longer_word():
    assert _has_marker("undelete.docx", "delete") is False


@pytest.mark.xfail(strict=True, reason="bool('false') is True")
def test_quoted_false_does_not_enable_folder_delete():
    config = build_moderate_delete_config(
        {"commands": {"moderate_delete": {"allow_folder_delete": "false"}}}
    )
    assert config.allow_folder_delete is False


@pytest.mark.xfail(strict=True, reason="negative max_per_run silently means unlimited")
def test_negative_max_per_run_is_rejected():
    with pytest.raises(ValueError):
        _validate_config(md_config(max_per_run=-1))
