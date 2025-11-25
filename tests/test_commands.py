import pytest
from src.drive_audit.commands import move_files_from_csv, move_files_to_public_folder
from src.drive_audit.model import DriveConfig


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


def test_move_files_to_public_folder_accepts_multiple_patterns(monkeypatch):
    drive_config = build_drive_config()

    public_calls = []

    def fake_ensure_public_subdir(service, parent_id, subdir_name, drive_id):
        public_calls.append(parent_id)
        return {"id": f"public-{parent_id}"}

    monkeypatch.setattr(
        "src.drive_audit.commands.ensure_public_subdir", fake_ensure_public_subdir
    )

    root_children = [
        {"id": "client", "name": "Client", "mimeType": "application/vnd.google-apps.folder", "parents": ["root"]},
        {"id": "loose", "name": "Loose", "mimeType": "text/plain", "parents": ["root"]},
    ]

    client_files = [
        {"id": "1", "name": "KP_report.xlsx", "mimeType": "application/vnd.ms-excel", "parents": ["client"]},
        {"id": "2", "name": "Public Report.csv", "mimeType": "text/csv", "parents": ["client"]},
        {"id": "3", "name": "notes.txt", "mimeType": "text/plain", "parents": ["client"]},
        {"id": "4", "name": "child", "mimeType": "application/vnd.google-apps.folder", "parents": ["client"]},
    ]

    def fake_list_folder_children(service, folder_id, drive_id):
        if folder_id == "root":
            return root_children
        if folder_id == "client":
            return client_files
        return []

    monkeypatch.setattr("src.drive_audit.commands.list_folder_children", fake_list_folder_children)

    moved = []

    def fake_move_file(service, file_id, new_parent, previous_parents):
        moved.append((file_id, new_parent, previous_parents))
        return {"file_id": file_id, "new_parent": new_parent, "previous_parents": previous_parents}

    monkeypatch.setattr("src.drive_audit.commands.move_file", fake_move_file)

    results = move_files_to_public_folder(
        None, drive_config, ["KP", "^Public Report\\.csv$"] , dry_run=False
    )

    assert len(results) == 2
    assert moved == [("1", "public-client", ["client"]), ("2", "public-client", ["client"])]
    assert public_calls == ["client"]


def test_move_files_to_public_folder_matches_case_insensitive(monkeypatch):
    drive_config = build_drive_config()

    public_calls = []

    def fake_ensure_public_subdir(service, parent_id, subdir_name, drive_id):
        public_calls.append(parent_id)
        return {"id": f"public-{parent_id}"}

    monkeypatch.setattr(
        "src.drive_audit.commands.ensure_public_subdir", fake_ensure_public_subdir
    )

    root_children = [
        {"id": "client", "name": "Client", "mimeType": "application/vnd.google-apps.folder", "parents": ["root"]},
    ]

    client_files = [
        {"id": "10", "name": "kp_summary.XLSX", "mimeType": "application/vnd.ms-excel", "parents": ["client"]},
    ]

    def fake_list_folder_children(service, folder_id, drive_id):
        if folder_id == "root":
            return root_children
        if folder_id == "client":
            return client_files
        return []

    monkeypatch.setattr("src.drive_audit.commands.list_folder_children", fake_list_folder_children)

    moved = []

    def fake_move_file(service, file_id, new_parent, previous_parents):
        moved.append((file_id, new_parent, previous_parents))
        return {"file_id": file_id, "new_parent": new_parent, "previous_parents": previous_parents}

    monkeypatch.setattr("src.drive_audit.commands.move_file", fake_move_file)

    results = move_files_to_public_folder(None, drive_config, ["kp.*\\.xlsx"], dry_run=False)

    assert len(results) == 1
    assert moved == [("10", "public-client", ["client"])]
    assert public_calls == ["client"]


def test_move_files_to_client_public_folder(monkeypatch):
    drive_config = build_drive_config()

    public_calls = []

    def fake_ensure_public_subdir(service, parent_id, subdir_name, drive_id):
        public_calls.append(parent_id)
        return {"id": f"public-{parent_id}", "name": subdir_name}

    monkeypatch.setattr(
        "src.drive_audit.commands.ensure_public_subdir", fake_ensure_public_subdir
    )

    root_children = [
        {"id": "client-a", "name": "Client A", "mimeType": "application/vnd.google-apps.folder", "parents": ["root"]},
        {"id": "client-b", "name": "Client B", "mimeType": "application/vnd.google-apps.folder", "parents": ["root"]},
    ]

    client_files = {
        "client-a": [
            {"id": "a1", "name": "KP_report.xlsx", "mimeType": "application/vnd.ms-excel", "parents": ["client-a"]},
        ],
        "client-b": [
            {"id": "b1", "name": "Public Report.csv", "mimeType": "text/csv", "parents": ["client-b"]},
        ],
    }

    def fake_list_folder_children(service, folder_id, drive_id):
        if folder_id == "root":
            return root_children
        return client_files.get(folder_id, [])

    monkeypatch.setattr("src.drive_audit.commands.list_folder_children", fake_list_folder_children)

    moved = []

    def fake_move_file(service, file_id, new_parent, previous_parents):
        moved.append((file_id, new_parent, previous_parents))
        return {"file_id": file_id, "new_parent": new_parent, "previous_parents": previous_parents}

    monkeypatch.setattr("src.drive_audit.commands.move_file", fake_move_file)

    results = move_files_to_public_folder(
        None, drive_config, ["KP", "^Public Report\\.csv$"] , dry_run=False
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
        "src.drive_audit.commands.ensure_public_subdir", lambda *args, **kwargs: {"id": "public"}
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
            return FakeRequest({"id": fileId, "name": "KP Client", "parents": ["old-parent"]})

    class FakeService:
        def __init__(self):
            self._files = FakeFilesResource()

        def files(self):
            return self._files

    moved = []

    def fake_move_file(service, file_id, new_parent, parents):
        moved.append((file_id, new_parent, parents))
        return {"file_id": file_id, "new_parent": new_parent, "parents": parents}

    monkeypatch.setattr("src.drive_audit.commands.move_file", fake_move_file)

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
