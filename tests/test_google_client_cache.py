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
    class _FakeFiles:
        def __init__(self):
            self.calls: list[Dict[str, str]] = []

        def ensure_public_subdir(self, parent_id: str, subdir_name: str, drive_id: str):
            self.calls.append(
                {
                    "parent_id": parent_id,
                    "subdir_name": subdir_name,
                    "drive_id": drive_id,
                }
            )
            return {"id": "existing", "name": subdir_name}

    fake_files = _FakeFiles()

    class _FakeFacade:
        def __init__(self, files):
            self.files = files

    monkeypatch.setattr(
        "drive_audit.google_client._with_facade",
        lambda service: _FakeFacade(fake_files),
    )

    folder = ensure_public_subdir(
        object(), parent_id="parent", subdir_name="public", drive_id="drive"
    )

    assert folder["id"] == "existing"
    assert fake_files.calls == [
        {"parent_id": "parent", "subdir_name": "public", "drive_id": "drive"}
    ]
