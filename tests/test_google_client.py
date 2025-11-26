from src.drive_audit.google_client import create_folder, list_files


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
