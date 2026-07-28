from unittest.mock import MagicMock

import pytest

import drive_audit.drive_activity as activity_module
from drive_audit.drive_activity import (
    ACTIVITY_SCOPES,
    PEOPLE_SCOPES,
    PEOPLE_USER_SCOPES,
    RenameActivityResolver,
    get_activity_service,
    get_people_service,
)
from drive_audit.model import DriveConfig


class Request:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.result


class FakeActivityResource:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def query(self, body):
        self.calls.append(body)
        token = body.get("pageToken", "")
        result = self.pages[token]
        if isinstance(result, Exception):
            return Request(error=result)
        return Request(result=result)


class FakeActivityService:
    def __init__(self, pages):
        self.resource = FakeActivityResource(pages)

    def activity(self):
        return self.resource


class FakePeopleResource:
    def __init__(self, profiles):
        self.profiles = profiles
        self.calls = []

    def get(self, resourceName, personFields):
        self.calls.append((resourceName, personFields))
        result = self.profiles[resourceName]
        if isinstance(result, Exception):
            return Request(error=result)
        return Request(result=result)


class FakePeopleService:
    def __init__(self, profiles):
        self.resource = FakePeopleResource(profiles)

    def people(self):
        return self.resource


class DummyCredentials:
    def __init__(self):
        self.subject = None

    def with_subject(self, subject):
        self.subject = subject
        return self


def drive_config(credentials_file="credentials.json", delegated_user="admin@test"):
    return DriveConfig(
        credentials_file=credentials_file,
        delegated_user=delegated_user,
        drive_id="drive",
        root_folder_id="drive",
        root_folder_name="root",
        include_trashed=False,
        include_shortcuts=True,
        max_depth=None,
        limit=None,
        public_subdir=None,
        output_dir="data",
        yaml_file="audit.yml",
        files_csv="files.csv",
        permissions_csv="permissions.csv",
    )


@pytest.mark.parametrize(
    ("factory", "api_name", "api_version", "expected_scopes", "expected_kwargs"),
    [
        (get_activity_service, "driveactivity", "v2", ACTIVITY_SCOPES, {}),
        (
            get_people_service,
            "people",
            "v1",
            PEOPLE_SCOPES,
            {"authorized_user_scopes": PEOPLE_USER_SCOPES},
        ),
    ],
)
def test_service_factories_use_isolated_scopes_and_delegation(
    monkeypatch,
    factory,
    api_name,
    api_version,
    expected_scopes,
    expected_kwargs,
):
    credentials = DummyCredentials()
    load_credentials = MagicMock(return_value=credentials)
    build = MagicMock(return_value="service")
    monkeypatch.setattr(activity_module, "load_credentials", load_credentials)
    monkeypatch.setattr(activity_module, "build", build)

    config = drive_config()
    result = factory(config)

    assert result == "service"
    load_credentials.assert_called_once_with(
        config,
        expected_scopes,
        **expected_kwargs,
    )
    build.assert_called_once_with(api_name, api_version, credentials=credentials)


@pytest.mark.parametrize("factory", [get_activity_service, get_people_service])
def test_service_factories_reject_missing_credentials(monkeypatch, factory):
    monkeypatch.setattr(
        activity_module,
        "load_credentials",
        MagicMock(side_effect=FileNotFoundError("missing")),
    )

    with pytest.raises(FileNotFoundError):
        factory(drive_config())


def rename_activity(
    old_name,
    new_name,
    timestamp,
    person_name="people/123",
    *,
    current_user=False,
):
    known_user = {"personName": person_name}
    if current_user:
        known_user = {"isCurrentUser": True}
    return {
        "primaryActionDetail": {"rename": {"oldTitle": old_name, "newTitle": new_name}},
        "actors": [{"user": {"knownUser": known_user}}],
        "timestamp": timestamp,
    }


def test_resolver_uses_singular_activity_resource_and_rename_filter():
    activity = FakeActivityService(
        {
            "": {
                "activities": [
                    rename_activity(
                        "report.docx",
                        "report +delete.docx",
                        "2026-07-27T10:00:00Z",
                    )
                ]
            }
        }
    )
    people = FakePeopleService(
        {
            "people/123": {
                "emailAddresses": [
                    {
                        "value": "renamer@example.com",
                        "metadata": {"primary": True},
                    }
                ],
                "names": [
                    {
                        "displayName": "Renamer",
                        "metadata": {"primary": True},
                    }
                ],
            }
        }
    )

    event = RenameActivityResolver(activity, people).resolve_rename(
        "file-1", "report +delete.docx", "+delete"
    )

    assert event is not None
    assert event.previous_name == "report.docx"
    assert event.new_name == "report +delete.docx"
    assert event.renamed_at == "2026-07-27T10:00:00Z"
    assert event.renamed_by == "renamer@example.com"
    assert event.renamer_domain == "example.com"
    call = activity.resource.calls[0]
    assert call["itemName"] == "items/file-1"
    assert call["filter"] == "detail.action_detail_case:RENAME"
    assert call["consolidationStrategy"] == {"none": {}}


def test_resolver_paginates_and_chooses_latest_matching_current_name():
    activity = FakeActivityService(
        {
            "": {
                "activities": [
                    rename_activity(
                        "old",
                        "different +delete",
                        "2026-07-27T12:00:00Z",
                    )
                ],
                "nextPageToken": "next",
            },
            "next": {
                "activities": [
                    rename_activity(
                        "original",
                        "target +delete",
                        "2026-07-27T11:00:00Z",
                    ),
                    rename_activity(
                        "older",
                        "target +delete",
                        "2026-07-27T09:00:00Z",
                    ),
                ]
            },
        }
    )
    people = FakePeopleService(
        {"people/123": {"emailAddresses": [{"value": "user@example.com"}]}}
    )
    resolver = RenameActivityResolver(activity, people)

    event = resolver.resolve_rename("file-1", "target +delete", "+delete")
    cached = resolver.resolve_rename("file-1", "target +delete", "+delete")

    assert event is not None
    assert event.previous_name == "original"
    assert cached == event
    assert len(activity.resource.calls) == 2
    assert activity.resource.calls[1]["pageToken"] == "next"
    assert len(people.resource.calls) == 1

    resolver.clear_activity_cache()
    resolver.resolve_rename("file-1", "target +delete", "+delete")
    assert len(activity.resource.calls) == 4
    assert len(people.resource.calls) == 1


def test_resolver_uses_time_range_and_current_user_fallback():
    activity = FakeActivityService(
        {
            "": {
                "activities": [
                    {
                        "primaryActionDetail": {
                            "rename": {
                                "oldTitle": "old",
                                "newTitle": "new +delete",
                            }
                        },
                        "actors": [{"user": {"knownUser": {"isCurrentUser": True}}}],
                        "timeRange": {
                            "startTime": "2026-07-27T08:00:00Z",
                            "endTime": "2026-07-27T08:01:00Z",
                        },
                    }
                ]
            }
        }
    )
    people = FakePeopleService({"people/me": RuntimeError("scope missing")})

    event = RenameActivityResolver(activity, people).resolve_rename(
        "file-1", "new +delete", "+delete"
    )

    assert event is not None
    assert event.renamed_at == "2026-07-27T08:01:00Z"
    assert event.renamed_by == "current-user"
    assert event.renamer_domain == ""


def test_resolver_returns_none_for_nonmatching_or_api_error():
    nonmatching = FakeActivityService(
        {
            "": {
                "activities": [
                    rename_activity("old", "new name", "2026-07-27T10:00:00Z")
                ]
            }
        }
    )
    people = FakePeopleService({})
    assert (
        RenameActivityResolver(nonmatching, people).resolve_rename(
            "file-1", "new name", "+delete"
        )
        is None
    )

    failing = FakeActivityService({"": RuntimeError("API unavailable")})
    assert (
        RenameActivityResolver(failing, people).resolve_rename(
            "file-1", "new +delete", "+delete"
        )
        is None
    )
