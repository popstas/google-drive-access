import json
from pathlib import Path

import pytest

from drive_audit.drive_client import get_drive_info, get_service
from drive_audit.model import DriveConfig


class DummyCreds:
    last_path = None
    last_scopes = None

    @classmethod
    def from_service_account_file(cls, path, scopes):
        cls.last_path = path
        cls.last_scopes = scopes
        return cls()

    def with_subject(self, subject):
        self.subject = subject
        return self


def _config(tmp_path: Path, delegated_user=None):
    credentials_file = tmp_path / "creds.json"
    credentials_file.write_text(json.dumps({"type": "service_account"}))
    return DriveConfig(
        credentials_file=str(credentials_file),
        delegated_user=delegated_user,
        drive_id="drive123",
        root_folder_id="root123",
        root_folder_name="Root",
        include_trashed=False,
        include_shortcuts=True,
        max_depth=None,
        limit=None,
        public_subdir=None,
        output_dir="./data",
        yaml_file="drive_audit.yml",
        files_csv="files.csv",
        permissions_csv="permissions.csv",
        list_folder_children_cache_timeout=3600,
    )


def test_get_service_builds_with_delegated_user(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "drive_audit.drive_client.service_account.Credentials", DummyCreds
    )
    built_with = {}

    def fake_build(api, version, credentials):
        built_with["api"] = api
        built_with["version"] = version
        built_with["credentials"] = credentials
        return "service"

    monkeypatch.setattr("drive_audit.drive_client.build", fake_build)

    config = _config(tmp_path, delegated_user="delegate@example.com")
    service = get_service(config)

    assert service == "service"
    assert DummyCreds.last_path == str(config.credentials_file)
    assert "drive" in DummyCreds.last_scopes[0]
    assert getattr(built_with["credentials"], "subject", None) == "delegate@example.com"


def test_get_drive_info_handles_user_and_shared_drive():
    class DummyAbout:
        def get(self, fields):
            self.fields = fields
            return self

        def execute(self):
            return {"about": True, "fields": self.fields}

    class DummyDrives:
        def __init__(self):
            self.called_with = None

        def get(self, driveId):
            self.called_with = driveId
            return self

        def execute(self):
            return {"drive": self.called_with}

    class DummyService:
        def __init__(self):
            self.about_client = DummyAbout()
            self.drives_client = DummyDrives()

        def about(self):
            return self.about_client

        def drives(self):
            return self.drives_client

    service = DummyService()

    user_info = get_drive_info(service, "")
    shared_info = get_drive_info(service, "drive123")

    assert user_info["about"] is True
    assert shared_info["drive"] == "drive123"
    assert service.drives_client.called_with == "drive123"
    assert service.about_client.fields == "user, storageQuota"
