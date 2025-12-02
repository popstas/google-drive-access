import csv
import importlib
import re
from pathlib import Path

import pytest

drive_links_info_module = importlib.import_module(
    "drive_audit.commands.drive_links_info"
)
from drive_audit.commands import (
    compare_files_by_location,
    drive_links_info,
    move_files_from_csv,
    move_files_to_public_folder,
)
from drive_audit.model import DriveConfig
from drive_audit.public_folder_ops import (
    collect_public_folder_matches,
    execute_public_folder_moves,
    validate_public_folder_move_inputs,
)


def build_drive_config() -> DriveConfig:
    return DriveConfig(
        credentials_file="creds.json",
        delegated_user=None,
        drive_id="drive",
        root_folder_id="root",
        root_folder_name="root",
        include_trashed=False,
        include_shortcuts=True,
        max_depth=None,
        limit=None,
        public_subdir="public",
        output_dir="./data",
        yaml_file="drive_audit.yml",
        files_csv="files.csv",
        permissions_csv="permissions.csv",
    )


def test_validate_public_folder_move_inputs_normalizes_values():
    drive_config = build_drive_config()

    patterns, mime_types = validate_public_folder_move_inputs(
        drive_config, "KP", ["text/csv", ""]
    )

    assert len(patterns) == 1
    assert patterns[0].pattern == "KP"
    assert mime_types == {"text/csv"}


def test_collect_public_folder_matches_filters_and_collects(monkeypatch):
    drive_config = build_drive_config()

    public_calls = []

    def fake_ensure_public_subdir(service, parent_id, subdir_name, drive_id):
        public_calls.append(parent_id)
        return {"id": f"public-{parent_id}", "name": subdir_name}

    monkeypatch.setattr(
        "drive_audit.public_folder_ops.ensure_public_subdir", fake_ensure_public_subdir
    )

    root_children = [
        {
            "id": "client",
            "name": "Client",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["root"],
        }
    ]

    client_files = [
        {
            "id": "1",
            "name": "KP_report.xlsx",
            "mimeType": "application/vnd.ms-excel",
            "parents": ["client"],
        },
        {
            "id": "2",
            "name": "notes.txt",
            "mimeType": "text/plain",
            "parents": ["client"],
        },
        {
            "id": "3",
            "name": "KP_report.xlsx",
            "mimeType": "application/vnd.ms-excel",
            "parents": ["public-client"],
        },
    ]

    def fake_list_folder_children(
        service, folder_id, drive_id, cache_timeout_seconds=None
    ):
        if folder_id == "root":
            return root_children
        if folder_id == "client":
            return client_files
        return []

    monkeypatch.setattr(
        "drive_audit.public_folder_ops.list_folder_children", fake_list_folder_children
    )

    patterns = [re.compile("KP", re.IGNORECASE)]
    matches = collect_public_folder_matches(None, drive_config, patterns, [])

    assert len(matches) == 1
    assert matches[0]["file"]["id"] == "1"
    assert public_calls == ["client"]


def test_execute_public_folder_moves_handles_dry_run_and_execute(monkeypatch):
    drive_config = build_drive_config()

    move_calls = []

    def fake_move_file(service, file_id, new_parent, previous_parents, drive_id=None):
        move_calls.append((file_id, new_parent, previous_parents, drive_id))
        return {
            "file_id": file_id,
            "new_parent": new_parent,
            "previous_parents": previous_parents,
        }

    monkeypatch.setattr("drive_audit.public_folder_ops.move_file", fake_move_file)

    matches = [
        {
            "file": {"id": "123", "name": "KP.pdf", "parents": ["client"]},
            "public_folder": {"id": "public-client", "name": "public"},
            "client_name": "Client",
        }
    ]

    dry_results = execute_public_folder_moves(None, matches, drive_config, dry_run=True)

    assert dry_results == [
        {
            "file_id": "123",
            "new_parent": "public-client",
            "destination_path": "Client/public",
            "dry_run": True,
        }
    ]
    assert move_calls == []

    live_results = execute_public_folder_moves(
        None, matches, drive_config, dry_run=False
    )

    assert live_results[0]["destination_path"] == "Client/public"
    assert move_calls == [("123", "public-client", ["client"], drive_config.drive_id)]


def test_compare_files_by_location_writes_differences(tmp_path: Path):
    csv_old = tmp_path / "old.csv"
    csv_new = tmp_path / "new.csv"

    old_rows = [
        {"location": "ClientA/File1", "name": "File1"},
        {"location": "ClientB/File2", "name": "File2"},
    ]
    new_rows = [
        {"location": "ClientB/File2", "name": "File2"},
        {"location": "ClientC/File3", "name": "File3"},
    ]

    with csv_old.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["location", "name"])
        writer.writeheader()
        writer.writerows(old_rows)

    with csv_new.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["location", "name"])
        writer.writeheader()
        writer.writerows(new_rows)

    outputs = compare_files_by_location(
        csv_old, csv_new, tmp_path / "only_new.csv", tmp_path / "only_old.csv"
    )

    with outputs["new"].open(encoding="utf-8") as handle:
        new_diff_rows = list(csv.DictReader(handle))
    with outputs["old"].open(encoding="utf-8") as handle:
        old_diff_rows = list(csv.DictReader(handle))

    assert new_diff_rows == [
        {
            "location": "ClientC/File3",
            "client_name": "",
            "mime_type": "",
            "modified": "",
        }
    ]
    assert old_diff_rows == [
        {
            "location": "ClientA/File1",
            "client_name": "",
            "mime_type": "",
            "modified": "",
        }
    ]


def test_compare_files_by_location_normalizes_google_and_office_formats(tmp_path: Path):
    csv_old = tmp_path / "old.csv"
    csv_new = tmp_path / "new.csv"

    old_rows = [
        {
            "location": "/Sandeep Koppula/Sandeep Koppula",
            "mimeType": "application/vnd.google-apps.spreadsheet",
        },
        {
            "location": "/Anita/Resume - Anna Petrovska.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    ]
    new_rows = [
        {
            "location": "/Sandeep Koppula/Sandeep Koppula.xlsx",
            "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
        {
            "location": "/Anita/Resume - Anna Petrovska",
            "mimeType": "application/vnd.google-apps.document",
        },
        {"location": "/Only/New", "mimeType": "text/plain"},
    ]

    with csv_old.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["location", "mimeType"])
        writer.writeheader()
        writer.writerows(old_rows)

    with csv_new.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["location", "mimeType"])
        writer.writeheader()
        writer.writerows(new_rows)

    outputs = compare_files_by_location(csv_old, csv_new)

    with outputs["new"].open(encoding="utf-8") as handle:
        new_diff_rows = list(csv.DictReader(handle))
    with outputs["old"].open(encoding="utf-8") as handle:
        old_diff_rows = list(csv.DictReader(handle))

    assert new_diff_rows == [
        {
            "location": "/Only/New",
            "client_name": "",
            "mime_type": "text/plain",
            "modified": "",
        }
    ]
    assert old_diff_rows == []


def test_compare_files_by_location_ignores_empty_folders(tmp_path: Path):
    csv_old = tmp_path / "old.csv"
    csv_new = tmp_path / "new.csv"

    # Old CSV: has an empty folder and a folder with files
    old_rows = [
        {
            "location": "/ClientA",
            "type": "folder",
            "mimeType": "application/vnd.google-apps.folder",
        },
        {
            "location": "/ClientA/File1.txt",
            "type": "file",
            "mimeType": "text/plain",
        },
        {
            "location": "/ClientB",
            "type": "folder",
            "mimeType": "application/vnd.google-apps.folder",
        },
        {
            "location": "/ClientC",
            "type": "folder",
            "mimeType": "application/vnd.google-apps.folder",
        },
    ]

    # New CSV: same structure but ClientB folder is removed
    new_rows = [
        {
            "location": "/ClientA",
            "type": "folder",
            "mimeType": "application/vnd.google-apps.folder",
        },
        {
            "location": "/ClientA/File1.txt",
            "type": "file",
            "mimeType": "text/plain",
        },
        {
            "location": "/ClientC",
            "type": "folder",
            "mimeType": "application/vnd.google-apps.folder",
        },
    ]

    with csv_old.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["location", "type", "mimeType"])
        writer.writeheader()
        writer.writerows(old_rows)

    with csv_new.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["location", "type", "mimeType"])
        writer.writeheader()
        writer.writerows(new_rows)

    # Test without ignore_empty_folders: empty folders should appear in differences
    outputs_without = compare_files_by_location(
        csv_old, csv_new, ignore_empty_folders=False
    )

    with outputs_without["old"].open(encoding="utf-8") as handle:
        old_diff_without = list(csv.DictReader(handle))

    # ClientB (empty folder) should appear in old-only differences
    old_locations_without = {row["location"] for row in old_diff_without}
    assert "/ClientB" in old_locations_without

    # Test with ignore_empty_folders: empty folders should be ignored
    outputs_with = compare_files_by_location(
        csv_old, csv_new, ignore_empty_folders=True
    )

    with outputs_with["old"].open(encoding="utf-8") as handle:
        old_diff_with = list(csv.DictReader(handle))
    with outputs_with["new"].open(encoding="utf-8") as handle:
        new_diff_with = list(csv.DictReader(handle))

    # ClientB (empty folder) should NOT appear in old-only differences
    old_locations_with = {row["location"] for row in old_diff_with}
    assert "/ClientB" not in old_locations_with

    # Verify stats show ignored empty folders
    stats = outputs_with["stats"]
    assert stats["ignored_empty_folders_old"] > 0
    assert stats["ignored_empty_folders_new"] >= 0


def test_move_files_to_public_folder_accepts_multiple_patterns(monkeypatch):
    drive_config = build_drive_config()

    public_calls = []

    def fake_ensure_public_subdir(service, parent_id, subdir_name, drive_id):
        public_calls.append(parent_id)
        return {"id": f"public-{parent_id}"}

    monkeypatch.setattr(
        "drive_audit.public_folder_ops.ensure_public_subdir", fake_ensure_public_subdir
    )

    root_children = [
        {
            "id": "client",
            "name": "Client",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["root"],
        },
        {"id": "loose", "name": "Loose", "mimeType": "text/plain", "parents": ["root"]},
    ]

    client_files = [
        {
            "id": "1",
            "name": "KP_report.xlsx",
            "mimeType": "application/vnd.ms-excel",
            "parents": ["client"],
        },
        {
            "id": "2",
            "name": "Public Report.csv",
            "mimeType": "text/csv",
            "parents": ["client"],
        },
        {
            "id": "3",
            "name": "notes.txt",
            "mimeType": "text/plain",
            "parents": ["client"],
        },
        {
            "id": "4",
            "name": "child",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["client"],
        },
    ]

    def fake_list_folder_children(
        service, folder_id, drive_id, cache_timeout_seconds=None
    ):
        if folder_id == "root":
            return root_children
        if folder_id == "client":
            return client_files
        return []

    monkeypatch.setattr(
        "drive_audit.public_folder_ops.list_folder_children", fake_list_folder_children
    )

    moved = []

    def fake_move_file(service, file_id, new_parent, previous_parents, drive_id=None):
        moved.append((file_id, new_parent, previous_parents))
        return {
            "file_id": file_id,
            "new_parent": new_parent,
            "previous_parents": previous_parents,
        }

    monkeypatch.setattr("drive_audit.public_folder_ops.move_file", fake_move_file)

    results = move_files_to_public_folder(
        None, drive_config, ["KP", "^Public Report\\.csv$"], dry_run=False
    )

    assert len(results) == 2
    assert moved == [
        ("1", "public-client", ["client"]),
        ("2", "public-client", ["client"]),
    ]
    assert public_calls == ["client"]


def test_move_files_to_public_folder_matches_case_insensitive(monkeypatch):
    drive_config = build_drive_config()

    public_calls = []

    def fake_ensure_public_subdir(service, parent_id, subdir_name, drive_id):
        public_calls.append(parent_id)
        return {"id": f"public-{parent_id}"}

    monkeypatch.setattr(
        "drive_audit.public_folder_ops.ensure_public_subdir", fake_ensure_public_subdir
    )

    root_children = [
        {
            "id": "client",
            "name": "Client",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["root"],
        },
    ]

    client_files = [
        {
            "id": "10",
            "name": "kp_summary.XLSX",
            "mimeType": "application/vnd.ms-excel",
            "parents": ["client"],
        },
    ]

    def fake_list_folder_children(
        service, folder_id, drive_id, cache_timeout_seconds=None
    ):
        if folder_id == "root":
            return root_children
        if folder_id == "client":
            return client_files
        return []

    monkeypatch.setattr(
        "drive_audit.public_folder_ops.list_folder_children", fake_list_folder_children
    )

    moved = []

    def fake_move_file(service, file_id, new_parent, previous_parents, drive_id=None):
        moved.append((file_id, new_parent, previous_parents))
        return {
            "file_id": file_id,
            "new_parent": new_parent,
            "previous_parents": previous_parents,
        }

    monkeypatch.setattr("drive_audit.public_folder_ops.move_file", fake_move_file)

    results = move_files_to_public_folder(
        None, drive_config, ["kp.*\\.xlsx"], dry_run=False
    )

    assert len(results) == 1
    assert moved == [("10", "public-client", ["client"])]
    assert public_calls == ["client"]


def test_move_files_to_public_folder_requires_both_name_and_mime(monkeypatch):
    drive_config = build_drive_config()

    def fake_ensure_public_subdir(service, parent_id, subdir_name, drive_id):
        return {"id": f"public-{parent_id}"}

    monkeypatch.setattr(
        "drive_audit.public_folder_ops.ensure_public_subdir", fake_ensure_public_subdir
    )

    root_children = [
        {
            "id": "client",
            "name": "Client",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["root"],
        },
    ]

    client_files = [
        {
            "id": "sheet",
            "name": "Plan.xlsx",
            "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "parents": ["client"],
        },
        {
            "id": "doc",
            "name": "Plan.xlsx",
            "mimeType": "application/vnd.google-apps.document",
            "parents": ["client"],
        },
    ]

    def fake_list_folder_children(
        service, folder_id, drive_id, cache_timeout_seconds=None
    ):
        if folder_id == "root":
            return root_children
        if folder_id == "client":
            return client_files
        return []

    monkeypatch.setattr(
        "drive_audit.public_folder_ops.list_folder_children", fake_list_folder_children
    )

    moved = []

    def fake_move_file(service, file_id, new_parent, previous_parents, drive_id=None):
        moved.append((file_id, new_parent, previous_parents))
        return {
            "file_id": file_id,
            "new_parent": new_parent,
            "previous_parents": previous_parents,
        }

    monkeypatch.setattr("drive_audit.public_folder_ops.move_file", fake_move_file)

    results = move_files_to_public_folder(
        None,
        drive_config,
        ["Plan\\.xlsx"],
        dry_run=False,
        mime_type_matches=[
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ],
    )

    assert len(results) == 1
    assert moved == [("sheet", "public-client", ["client"])]


def test_move_files_to_client_public_folder(monkeypatch):
    drive_config = build_drive_config()

    public_calls = []

    def fake_ensure_public_subdir(service, parent_id, subdir_name, drive_id):
        public_calls.append(parent_id)
        return {"id": f"public-{parent_id}", "name": subdir_name}

    monkeypatch.setattr(
        "drive_audit.public_folder_ops.ensure_public_subdir", fake_ensure_public_subdir
    )

    root_children = [
        {
            "id": "client-a",
            "name": "Client A",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["root"],
        },
        {
            "id": "client-b",
            "name": "Client B",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["root"],
        },
    ]

    client_files = {
        "client-a": [
            {
                "id": "a1",
                "name": "KP_report.xlsx",
                "mimeType": "application/vnd.ms-excel",
                "parents": ["client-a"],
            },
        ],
        "client-b": [
            {
                "id": "b1",
                "name": "Public Report.csv",
                "mimeType": "text/csv",
                "parents": ["client-b"],
            },
        ],
    }

    def fake_list_folder_children(
        service, folder_id, drive_id, cache_timeout_seconds=None
    ):
        if folder_id == "root":
            return root_children
        return client_files.get(folder_id, [])

    monkeypatch.setattr(
        "drive_audit.public_folder_ops.list_folder_children", fake_list_folder_children
    )

    moved = []

    def fake_move_file(service, file_id, new_parent, previous_parents, drive_id=None):
        moved.append((file_id, new_parent, previous_parents))
        return {
            "file_id": file_id,
            "new_parent": new_parent,
            "previous_parents": previous_parents,
        }

    monkeypatch.setattr("drive_audit.public_folder_ops.move_file", fake_move_file)

    results = move_files_to_public_folder(
        None, drive_config, ["KP", "^Public Report\\.csv$"], dry_run=False
    )

    assert len(results) == 2
    assert moved == [
        ("a1", "public-client-a", ["client-a"]),
        ("b1", "public-client-b", ["client-b"]),
    ]
    assert public_calls == ["client-a", "client-b"]


def test_move_files_to_public_folder_requires_patterns(monkeypatch):
    drive_config = build_drive_config()
    monkeypatch.setattr(
        "drive_audit.public_folder_ops.ensure_public_subdir",
        lambda *args, **kwargs: {"id": "public"},
    )

    with pytest.raises(ValueError, match="file_matches"):
        move_files_to_public_folder(None, drive_config, [], dry_run=False)


def test_move_files_from_csv_moves_listed_files(tmp_path, monkeypatch):
    csv_file = tmp_path / "move_files.csv"
    csv_file.write_text(
        "file_name,file_id,dest_folder,source_folder\n"
        "KP Client,file-1,destination-folder,client-folder\n",
        encoding="utf-8",
    )

    drive_config = build_drive_config()

    class FakeRequest:
        def __init__(self, response):
            self.response = response

        def execute(self):
            return self.response

    class FakeFilesResource:
        def get(self, fileId, fields, supportsAllDrives):
            assert fields == "id,name,parents"
            assert supportsAllDrives is True
            return FakeRequest(
                {"id": fileId, "name": "KP Client", "parents": ["old-parent"]}
            )

    class FakeService:
        def __init__(self):
            self._files = FakeFilesResource()

        def files(self):
            return self._files

    moved = []

    def fake_move_file(service, file_id, new_parent, parents, drive_id=None):
        moved.append((file_id, new_parent, parents))
        return {"file_id": file_id, "new_parent": new_parent, "parents": parents}

    monkeypatch.setattr("drive_audit.commands.move_from_csv.move_file", fake_move_file)

    results = move_files_from_csv(FakeService(), drive_config, csv_file, dry_run=False)

    assert results == [
        {
            "file_id": "file-1",
            "new_parent": "destination-folder",
            "parents": ["old-parent"],
            "destination_parent": "destination-folder",
        }
    ]
    assert moved == [("file-1", "destination-folder", ["old-parent"])]


def test_drive_links_info_retrieves_folder_metadata(tmp_path, monkeypatch):
    """Test that drive_links_info correctly retrieves folder metadata from URLs and preserves original columns."""
    # Create test CSV with folder URLs
    csv_file = tmp_path / "test_contacts.csv"
    csv_file.write_text(
        "Name,Contact ID,Folder URL\n"
        "Client A,12345,https://drive.google.com/drive/folders/folder123\n"
        "Client B,67890,https://drive.google.com/drive/folders/folder456\n"
        "Client C,11111,\n",
        encoding="utf-8",
    )

    output_file = tmp_path / "output.csv"

    # Mock service.files().get() calls
    class FakeFiles:
        def get(self, fileId, fields, supportsAllDrives):
            if fileId == "folder123":
                return FakeExecute(
                    {
                        "id": "folder123",
                        "name": "Client A Folder",
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": ["parent1"],
                        "createdTime": "2025-01-01T00:00:00.000Z",
                        "modifiedTime": "2025-01-02T00:00:00.000Z",
                        "owners": [{"emailAddress": "owner@example.com"}],
                        "lastModifyingUser": {"emailAddress": "user@example.com"},
                        "webViewLink": "https://drive.google.com/drive/folders/folder123",
                    }
                )
            elif fileId == "folder456":
                return FakeExecute(
                    {
                        "id": "folder456",
                        "name": "Client B Folder",
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": ["parent2"],
                        "createdTime": "2025-01-03T00:00:00.000Z",
                        "modifiedTime": "2025-01-04T00:00:00.000Z",
                        "owners": [{"emailAddress": "owner2@example.com"}],
                        "lastModifyingUser": {"emailAddress": "user2@example.com"},
                        "webViewLink": "https://drive.google.com/drive/folders/folder456",
                    }
                )
            raise Exception(f"Unknown folder ID: {fileId}")

    class FakeExecute:
        def __init__(self, data):
            self.data = data

        def execute(self):
            return self.data

    class FakeService:
        def files(self):
            return FakeFiles()

    # Mock get_file_permissions
    def fake_get_permissions(service, file_id):
        return [{"type": "user", "role": "reader"}]

    monkeypatch.setattr(
        drive_links_info_module,
        "get_file_permissions",
        fake_get_permissions,
    )

    # Run the command with cache disabled for test
    drive_links_info(
        FakeService(),
        csv_file=csv_file,
        column="Folder URL",
        output_path=output_file,
        cache_timeout_seconds=0,  # Disable cache for test
    )

    # Verify output
    assert output_file.exists()

    with output_file.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 3

    # Check first row - has Drive metadata
    assert rows[0]["source_row"] == "2"
    assert rows[0]["Name"] == "Client A"
    assert rows[0]["Contact ID"] == "12345"
    assert rows[0]["folder_id"] == "folder123"
    assert rows[0]["folder_name"] == "Client A Folder"
    assert rows[0]["owner_emails"] == "owner@example.com"
    assert rows[0]["permissions_count"] == "1"

    # Check second row - has Drive metadata
    assert rows[1]["source_row"] == "3"
    assert rows[1]["Name"] == "Client B"
    assert rows[1]["Contact ID"] == "67890"
    assert rows[1]["folder_id"] == "folder456"
    assert rows[1]["folder_name"] == "Client B Folder"
    assert rows[1]["owner_emails"] == "owner2@example.com"
    assert rows[1]["permissions_count"] == "1"

    # Check third row - empty URL, should have original columns but empty Drive metadata
    assert rows[2]["source_row"] == "4"
    assert rows[2]["Name"] == "Client C"
    assert rows[2]["Contact ID"] == "11111"
    assert rows[2]["folder_id"] == ""
    assert rows[2]["folder_name"] == ""


def test_drive_links_info_handles_errors(tmp_path, monkeypatch):
    """Test that drive_links_info handles errors gracefully and preserves original columns."""
    # Create test CSV with invalid URLs
    csv_file = tmp_path / "test_contacts.csv"
    csv_file.write_text(
        "Name,Contact ID,Folder URL\n"
        "Client A,12345,not-a-valid-url\n"
        "Client B,67890,https://drive.google.com/drive/folders/error-folder\n",
        encoding="utf-8",
    )

    output_file = tmp_path / "output.csv"

    # Mock service.files().get() to raise error
    class FakeFiles:
        def get(self, fileId, fields, supportsAllDrives):
            raise Exception("API Error")

    class FakeService:
        def files(self):
            return FakeFiles()

    def fake_get_permissions(service, file_id):
        return []

    monkeypatch.setattr(
        drive_links_info_module,
        "get_file_permissions",
        fake_get_permissions,
    )

    # Run the command - should not raise exception
    drive_links_info(
        FakeService(),
        csv_file=csv_file,
        column="Folder URL",
        output_path=output_file,
        cache_timeout_seconds=0,  # Disable cache for test
    )

    # Verify output exists and contains error rows
    assert output_file.exists()

    with output_file.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2

    # Both rows should have errors and preserve original columns
    assert "error" in rows[0]
    assert rows[0]["Name"] == "Client A"
    assert rows[0]["Contact ID"] == "12345"
    assert rows[0]["folder_id"] == ""

    assert "error" in rows[1]
    assert rows[1]["Name"] == "Client B"
    assert rows[1]["Contact ID"] == "67890"
    assert rows[1]["folder_id"] == ""
