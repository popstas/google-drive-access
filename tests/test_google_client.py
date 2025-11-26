from src.drive_audit.google_client import (
    create_folder,
    DEFAULT_LIST_CHILDREN_CACHE_DIR,
    list_files,
    list_folder_children,
    move_file,
    reset_list_folder_children_cache,
    set_list_folder_children_cache_dir,
)


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


class _FakeFilesCreate:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeRequest({"id": "new", "name": kwargs["body"]["name"]})


class _FakeServiceListOnly:
    def __init__(self, responses):
        self.files_api = _FakeFilesList(responses)

    def files(self):
        return self.files_api


class _FakeServiceCreateOnly:
    def __init__(self):
        self.files_api = _FakeFilesCreate()

    def files(self):
        return self.files_api


class _FakeFilesListAndUpdate:
    def __init__(self, responses):
        self.list_api = _FakeFilesList(responses)
        self.update_calls = []

    def list(self, **kwargs):
        return self.list_api.list(**kwargs)

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return _FakeRequest({"id": kwargs.get("fileId"), "parents": [kwargs.get("addParents")]})


class _FakeServiceWithUpdate:
    def __init__(self, responses):
        self.files_api = _FakeFilesListAndUpdate(responses)

    def files(self):
        return self.files_api


def test_list_files_uses_user_drive_when_drive_id_missing():
    responses = [{"files": []}]
    service = _FakeServiceListOnly(responses)

    list(list_files(service, "", page_size=5))

    assert len(service.files_api.calls) == 1
    call = service.files_api.calls[0]
    assert call["corpora"] == "user"
    assert "driveId" not in call
    assert "includeItemsFromAllDrives" not in call
    assert "supportsAllDrives" not in call


def test_create_folder_omits_drive_scoping_when_missing_drive_id():
    service = _FakeServiceCreateOnly()

    created = create_folder(service, "parent", "child", "")

    assert created["id"] == "new"
    assert len(service.files_api.calls) == 1
    call = service.files_api.calls[0]
    assert call["body"]["parents"] == ["parent"]
    assert "driveId" not in call["body"]
    assert call["supportsAllDrives"] is False


def test_list_folder_children_uses_cache():
    reset_list_folder_children_cache()
    responses = [
        {"files": [{"id": "child", "name": "Child", "mimeType": "text/plain", "parents": ["folder"]}]},
        {"files": []},
    ]
    service = _FakeServiceListOnly(responses)

    first = list(
        list_folder_children(
            service, "folder", "drive", page_size=50, cache_timeout_seconds=3600
        )
    )
    second = list(
        list_folder_children(
            service, "folder", "drive", page_size=50, cache_timeout_seconds=3600
        )
    )

    assert first == second
    assert len(service.files_api.calls) == 1


def test_move_file_clears_cached_children():
    reset_list_folder_children_cache()
    responses = [
        {"files": [{"id": "child", "name": "Child", "mimeType": "text/plain", "parents": ["source"]}]},
        {"files": []},
        {"files": [{"id": "child", "name": "Child", "mimeType": "text/plain", "parents": ["source"]}]},
        {"files": [{"id": "moved", "name": "Moved", "mimeType": "text/plain", "parents": ["destination"]}]},
    ]
    service = _FakeServiceWithUpdate(responses)

    list(
        list_folder_children(
            service, "source", "drive", page_size=100, cache_timeout_seconds=3600
        )
    )
    list(
        list_folder_children(
            service, "destination", "drive", page_size=100, cache_timeout_seconds=3600
        )
    )

    assert len(service.files_api.list_api.calls) == 2

    move_file(service, "file-1", "destination", ["source"], drive_id="drive")

    list(
        list_folder_children(
            service, "source", "drive", page_size=100, cache_timeout_seconds=3600
        )
    )
    list(
        list_folder_children(
            service, "destination", "drive", page_size=100, cache_timeout_seconds=3600
        )
    )

    assert len(service.files_api.list_api.calls) == 4


def test_list_folder_children_persists_to_disk(tmp_path):
    cache_dir = tmp_path / "list_children"
    set_list_folder_children_cache_dir(cache_dir)
    reset_list_folder_children_cache()

    responses = [
        {"files": [{"id": "child", "name": "Child", "mimeType": "text/plain", "parents": ["folder"]}]},
    ]
    service = _FakeServiceListOnly(responses)

    first = list(
        list_folder_children(
            service, "folder", "drive", page_size=50, cache_timeout_seconds=3600
        )
    )

    assert len(service.files_api.calls) == 1

    set_list_folder_children_cache_dir(cache_dir)
    second_service = _FakeServiceListOnly([])
    second = list(
        list_folder_children(
            second_service, "folder", "drive", page_size=50, cache_timeout_seconds=3600
        )
    )

    assert first == second
    assert len(second_service.files_api.calls) == 0

    set_list_folder_children_cache_dir(DEFAULT_LIST_CHILDREN_CACHE_DIR)
    reset_list_folder_children_cache()
