import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from drive_audit import credentials as credentials_module
from drive_audit.credentials import load_credentials
from drive_audit.model import DriveConfig


def drive_config(path: Path, delegated_user=None) -> DriveConfig:
    return DriveConfig(
        credentials_file=str(path),
        delegated_user=delegated_user,
        drive_id="",
        root_folder_id="root",
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


def test_loads_service_account_and_applies_delegation(monkeypatch, tmp_path):
    path = tmp_path / "service-account.json"
    path.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")
    delegated = MagicMock()
    credentials = MagicMock()
    credentials.with_subject.return_value = delegated
    factory = MagicMock(return_value=credentials)
    monkeypatch.setattr(
        credentials_module.service_account.Credentials,
        "from_service_account_file",
        factory,
    )

    config = drive_config(path, delegated_user="admin@example.com")
    result = load_credentials(config, ["scope-a"])

    assert result is delegated
    factory.assert_called_once_with(str(path), scopes=["scope-a"])
    credentials.with_subject.assert_called_once_with("admin@example.com")


def test_loads_authorized_user_with_granted_scopes(monkeypatch, tmp_path):
    path = tmp_path / "authorized-user.json"
    path.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
    credentials = MagicMock(scopes=["scope-a", "scope-b"])
    factory = MagicMock(return_value=credentials)
    monkeypatch.setattr(
        credentials_module.user_credentials.Credentials,
        "from_authorized_user_file",
        factory,
    )

    result = load_credentials(drive_config(path), ["scope-a"])

    assert result is credentials
    factory.assert_called_once_with(str(path))


def test_authorized_user_supports_alternative_people_scopes(
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "authorized-user.json"
    path.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
    credentials = MagicMock(scopes=["userinfo.email", "userinfo.profile"])
    monkeypatch.setattr(
        credentials_module.user_credentials.Credentials,
        "from_authorized_user_file",
        MagicMock(return_value=credentials),
    )

    result = load_credentials(
        drive_config(path),
        ["directory.readonly"],
        authorized_user_scopes=["userinfo.email", "userinfo.profile"],
    )

    assert result is credentials


def test_authorized_user_rejects_missing_scope(monkeypatch, tmp_path):
    path = tmp_path / "authorized-user.json"
    path.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
    credentials = MagicMock(scopes=["scope-a"])
    monkeypatch.setattr(
        credentials_module.user_credentials.Credentials,
        "from_authorized_user_file",
        MagicMock(return_value=credentials),
    )

    with pytest.raises(ValueError, match="scope-b"):
        load_credentials(drive_config(path), ["scope-a", "scope-b"])


def test_authorized_user_rejects_delegated_user(monkeypatch, tmp_path):
    path = tmp_path / "authorized-user.json"
    path.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")

    with pytest.raises(ValueError, match="only supported for service-account"):
        load_credentials(
            drive_config(path, delegated_user="admin@example.com"),
            ["scope-a"],
        )


def test_rejects_unknown_type(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"type": "external_account"}), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported Google credentials type"):
        load_credentials(drive_config(path), ["scope-a"])
