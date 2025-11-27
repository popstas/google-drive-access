from drive_audit.drive_permissions import DrivePermissions


class _FakePermissionsApi:
    def __init__(self, list_responses, create_response=None):
        self.list_responses = list(list_responses)
        self.list_calls = []
        self.create_calls = []
        self.create_response = create_response or {"id": "new"}

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        response = self.list_responses.pop(0)
        return _FakeRequest(response)

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return _FakeRequest(self.create_response)


class _FakeRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeService:
    def __init__(self, list_responses, create_response=None):
        self.permissions_api = _FakePermissionsApi(list_responses, create_response)

    def permissions(self):
        return self.permissions_api


def test_get_file_permissions_handles_pagination():
    service = _FakeService(
        [
            {"permissions": [{"id": 1}], "nextPageToken": "next"},
            {"permissions": [{"id": 2}]},
        ]
    )
    permissions = DrivePermissions(service).get_file_permissions("file")

    assert permissions == [{"id": 1}, {"id": 2}]
    assert len(service.permissions_api.list_calls) == 2


def test_add_user_permission_converts_role():
    service = _FakeService([{"permissions": []}])
    DrivePermissions(service).add_user_permission(
        "file", "user@example.com", "organizer"
    )

    assert service.permissions_api.create_calls[0]["body"]["role"] == "fileOrganizer"


def test_ensure_public_permission_reuses_existing():
    service = _FakeService([{"permissions": [{"id": "anyone", "type": "anyone"}]}])
    permission = DrivePermissions(service).ensure_public_permission("file")

    assert permission["id"] == "anyone"
    assert len(service.permissions_api.create_calls) == 0


def test_ensure_public_permission_creates_when_missing():
    service = _FakeService(
        [
            {"permissions": []},
            {"permissions": []},
        ],
        create_response={"id": "created"},
    )
    permission = DrivePermissions(service).ensure_public_permission("file")

    assert permission["id"] == "created"
    assert len(service.permissions_api.create_calls) == 1
