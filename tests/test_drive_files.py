from drive_audit.drive_cache import ListFolderChildrenCache
from drive_audit.drive_files import DriveFiles
from drive_audit.drive_permissions import DrivePermissions


class _FakeRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeFilesList:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        return _FakeRequest(response)

    def update(self, **kwargs):
        raise AssertionError("Update should not be called on list-only fake")


class _FakeFilesCreate(_FakeFilesList):
    def __init__(self, responses=None):
        super().__init__(responses or [])
        self.create_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return _FakeRequest({"id": "new", "name": kwargs["body"]["name"]})


class _FakeFilesListAndUpdate(_FakeFilesList):
    def __init__(self, responses):
        super().__init__(responses)
        self.list_api = self
        self.update_calls = []

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return _FakeRequest(
            {"id": kwargs.get("fileId"), "parents": [kwargs.get("addParents")]}
        )


class _FakeService:
    def __init__(self, files_api):
        self.files_api = files_api

    def files(self):
        return self.files_api


class _FakePermissions(DrivePermissions):
    def __init__(self):
        self.ensure_calls = []

    def ensure_public_permission(self, file_id: str):
        self.ensure_calls.append(file_id)
        return {"id": file_id}


def test_list_files_uses_user_drive_when_drive_id_missing():
    responses = [{"files": []}]
    files_api = _FakeFilesList(responses)
    service = _FakeService(files_api)

    list(
        DriveFiles(service, cache=ListFolderChildrenCache()).list_files("", page_size=5)
    )

    assert len(files_api.calls) == 1
    call = files_api.calls[0]
    assert call["corpora"] == "user"
    assert "driveId" not in call
    assert "includeItemsFromAllDrives" not in call
    assert "supportsAllDrives" not in call


def test_create_folder_omits_drive_scoping_when_missing_drive_id():
    files_api = _FakeFilesCreate()
    service = _FakeService(files_api)
    manager = DriveFiles(service, cache=ListFolderChildrenCache())

    created = manager.create_folder("parent", "child", "")

    assert created["id"] == "new"
    assert len(files_api.create_calls) == 1
    call = files_api.create_calls[0]
    assert call["body"]["parents"] == ["parent"]
    assert "driveId" not in call["body"]
    assert call["supportsAllDrives"] is False


def test_list_files_with_drive_id_uses_drive_corpora_and_limits_page_size():
    responses = [
        {"files": [{"id": "a"}]},
        {"files": []},
    ]
    files_api = _FakeFilesList(responses)
    service = _FakeService(files_api)

    # limit smaller than page size forces adjusted page size
    list(
        DriveFiles(service, cache=ListFolderChildrenCache()).list_files(
            "drive-123", page_size=50, limit=1
        )
    )

    assert len(files_api.calls) == 1
    call = files_api.calls[0]
    assert call["corpora"] == "drive"
    assert call["driveId"] == "drive-123"
    assert call["includeItemsFromAllDrives"] is True
    assert call["supportsAllDrives"] is True
    assert call["pageSize"] == 1


def test_list_folder_children_uses_cache(tmp_path):
    cache = ListFolderChildrenCache(tmp_path / "cache")
    responses = [
        {
            "files": [
                {
                    "id": "child",
                    "name": "Child",
                    "mimeType": "text/plain",
                    "parents": ["folder"],
                }
            ]
        },
        {"files": []},
    ]
    files_api = _FakeFilesList(responses)
    service = _FakeService(files_api)
    manager = DriveFiles(service, cache=cache)

    first = list(
        manager.list_folder_children(
            "folder", "drive", page_size=50, cache_timeout_seconds=3600
        )
    )
    second = list(
        manager.list_folder_children(
            "folder", "drive", page_size=50, cache_timeout_seconds=3600
        )
    )

    assert first == second
    assert len(files_api.calls) == 1


def test_move_file_clears_cached_children(tmp_path):
    cache = ListFolderChildrenCache(tmp_path / "cache")
    responses = [
        {
            "files": [
                {
                    "id": "child",
                    "name": "Child",
                    "mimeType": "text/plain",
                    "parents": ["source"],
                }
            ]
        },
        {"files": []},
        {
            "files": [
                {
                    "id": "child",
                    "name": "Child",
                    "mimeType": "text/plain",
                    "parents": ["source"],
                }
            ]
        },
        {
            "files": [
                {
                    "id": "moved",
                    "name": "Moved",
                    "mimeType": "text/plain",
                    "parents": ["destination"],
                }
            ]
        },
    ]
    files_api = _FakeFilesListAndUpdate(responses)
    service = _FakeService(files_api)
    manager = DriveFiles(service, cache=cache)

    list(
        manager.list_folder_children(
            "source", "drive", page_size=100, cache_timeout_seconds=3600
        )
    )
    list(
        manager.list_folder_children(
            "destination", "drive", page_size=100, cache_timeout_seconds=3600
        )
    )

    assert len(files_api.list_api.calls) == 2

    manager.move_file("file-1", "destination", ["source"], drive_id="drive")

    list(
        manager.list_folder_children(
            "source", "drive", page_size=100, cache_timeout_seconds=3600
        )
    )
    list(
        manager.list_folder_children(
            "destination", "drive", page_size=100, cache_timeout_seconds=3600
        )
    )

    assert len(files_api.list_api.calls) == 4


def test_ensure_public_subdir_delegates_to_permissions(tmp_path):
    cache = ListFolderChildrenCache(tmp_path / "cache")
    files_api = _FakeFilesCreate(
        [
            {"files": []},  # First list() call (exact match query)
            {"files": []},  # Second list() call (fallback query)
        ]
    )
    service = _FakeService(files_api)
    permissions = _FakePermissions()
    manager = DriveFiles(service, cache=cache, permissions=permissions)

    folder = manager.ensure_public_subdir("parent", "public", "drive")

    assert folder["name"] == "public"
    assert permissions.ensure_calls == [folder["id"]]
