import csv
import sys
from pathlib import Path

import pytest

from drive_audit.commands import main as commands_main
from drive_audit.commands.filter_permissions import filter_permissions


def _write_permissions_csv(path: Path) -> None:
    rows = [
        {
            "file_id": "1",
            "permission_email": "user1@example.com",
            "permission_role": "reader",
        },
        {
            "file_id": "2",
            "permission_email": "user2@example.com",
            "permission_role": "writer",
        },
        {
            "file_id": "3",
            "permission_email": "",
            "permission_role": "reader",
        },
        {
            "file_id": "4",
            "permission_email": "USER2@EXAMPLE.COM",
            "permission_role": "commenter",
        },
    ]

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["file_id", "permission_email", "permission_role"]
        )
        writer.writeheader()
        writer.writerows(rows)


def test_filter_permissions_writes_matching_rows(tmp_path: Path) -> None:
    csv_in = tmp_path / "permissions.csv"
    csv_out = tmp_path / "filtered.csv"
    _write_permissions_csv(csv_in)

    stats = filter_permissions(
        csv_file=csv_in,
        csv_save=csv_out,
        permission_emails={"user2@example.com"},
    )

    assert stats == {"total_rows": 4, "matched_rows": 2}
    assert csv_out.exists()

    with csv_out.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert [row["file_id"] for row in rows] == ["2", "4"]


def test_filter_permissions_command_runs_without_google_config(tmp_path, monkeypatch):
    csv_in = tmp_path / "permissions.csv"
    csv_out = tmp_path / "filtered.csv"
    _write_permissions_csv(csv_in)

    cfg = tmp_path / "config.yml"
    cfg.write_text("logLevel: INFO\n", encoding="utf-8")

    monkeypatch.setattr(
        "drive_audit.commands.get_service",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("get_service should not be called for filter_permissions")
        ),
    )
    monkeypatch.setattr("drive_audit.commands.configure_logger", lambda **_kwargs: None)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--config",
            str(cfg),
            "filter_permissions",
            "--emails",
            "user1@example.com",
            "--csv-file",
            str(csv_in),
            "--csv-save",
            str(csv_out),
        ],
    )

    commands_main()

    assert csv_out.exists()
    with csv_out.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["file_id"] for row in rows] == ["1"]
