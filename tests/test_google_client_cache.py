from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from drive_audit.google_client import (
    ensure_public_subdir,
    list_folder_children,
    reset_list_folder_children_cache,
    set_list_folder_children_cache_dir,
)


class FakeRequest:
    def __init__(self, response: Dict):
        self.response = response

    def execute(self) -> Dict:
        return self.response


class FakeFilesResource:
    def __init__(self, pages: List[Dict]):
        self.pages = list(pages)
        self.calls = 0

    def list(self, **kwargs):
        response = (
            self.pages[self.calls] if self.calls < len(self.pages) else {"files": []}
        )
        self.calls += 1
        return FakeRequest(response)


class FakeService:
    def __init__(self, pages: List[Dict]):
        self.files_resource = FakeFilesResource(pages)

    def files(self):
        return self.files_resource


def test_list_folder_children_caches_results(tmp_path: Path):
    set_list_folder_children_cache_dir(tmp_path)
    reset_list_folder_children_cache()

    pages = [
        {
            "files": [
                {
                    "id": "1",
                    "name": "first",
                    "mimeType": "text/plain",
                    "parents": ["folder"],
                },
            ],
            "nextPageToken": "next",
        },
        {
            "files": [
                {
                    "id": "2",
                    "name": "second",
                    "mimeType": "text/plain",
                    "parents": ["folder"],
                }
            ]
        },
    ]
    service = FakeService(pages)

    first_pass = list(
        list_folder_children(
            service,
            folder_id="folder",
            drive_id="drive",
            page_size=10,
            cache_timeout_seconds=3600,
        )
    )

    assert [file["id"] for file in first_pass] == ["1", "2"]
    assert service.files_resource.calls == 2
    assert list(tmp_path.glob("*.json"))

    second_pass = list(
        list_folder_children(
            service,
            folder_id="folder",
            drive_id="drive",
            page_size=10,
            cache_timeout_seconds=3600,
        )
    )

    assert [file["id"] for file in second_pass] == ["1", "2"]
    assert service.files_resource.calls == 2


def test_list_folder_children_skips_cache_when_disabled(tmp_path: Path):
    set_list_folder_children_cache_dir(tmp_path)
    reset_list_folder_children_cache()

    first_pages = [
        {
            "files": [
                {
                    "id": "cached",
                    "name": "cached",
                    "mimeType": "text/plain",
                    "parents": ["folder"],
                }
            ]
        }
    ]
    first_pass = list(
        list_folder_children(
            FakeService(first_pages),
            folder_id="folder",
            drive_id="",
            page_size=5,
            cache_timeout_seconds=0,
        )
    )
    second_pages = [
        {
            "files": [
                {
                    "id": "cached",
                    "name": "cached",
                    "mimeType": "text/plain",
                    "parents": ["folder"],
                }
            ]
        }
    ]
    second_pass = list(
        list_folder_children(
            FakeService(second_pages),
            folder_id="folder",
            drive_id="",
            page_size=5,
            cache_timeout_seconds=0,
        )
    )

    assert [file["id"] for file in first_pass] == ["cached"]
    assert [file["id"] for file in second_pass] == ["cached"]
    assert not list(tmp_path.glob("*.json"))


def test_ensure_public_subdir_reuses_existing(monkeypatch):
    created: Dict[str, Dict] = {}
    ensured: list[str] = []

    def fake_find_child_folder(service, parent_id, name, drive_id):
        created["last_lookup"] = {
            "parent_id": parent_id,
            "name": name,
            "drive_id": drive_id,
        }
        return {"id": "existing", "name": name}

    def fake_create_folder(service, parent_id, name, drive_id):
        created["created"] = {
            "parent_id": parent_id,
            "name": name,
            "drive_id": drive_id,
        }
        return {"id": "new", "name": name}

    def fake_ensure_public_permission(service, file_id):
        ensured.append(file_id)
        return {"id": file_id}

    monkeypatch.setattr(
        "drive_audit.google_client.find_child_folder", fake_find_child_folder
    )
    monkeypatch.setattr("drive_audit.google_client.create_folder", fake_create_folder)
    monkeypatch.setattr(
        "drive_audit.google_client.ensure_public_permission",
        fake_ensure_public_permission,
    )

    folder = ensure_public_subdir(
        None, parent_id="parent", subdir_name="public", drive_id="drive"
    )

    assert folder["id"] == "existing"
    assert "created" not in created
    assert ensured == ["existing"]
