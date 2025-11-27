from datetime import datetime

import yaml

from drive_audit.export_yaml import format_datetime, save_yaml
from drive_audit.model import (
    AccessInfo,
    DriveConfig,
    FileInfo,
    Permission,
    PermissionDetails,
    PolicyInfo,
)


def _config():
    return DriveConfig(
        credentials_file="creds.json",
        delegated_user=None,
        drive_id="drive123",
        root_folder_id="root123",
        root_folder_name="Root",
        include_trashed=False,
        include_shortcuts=True,
        max_depth=5,
        limit=None,
        public_subdir=None,
        output_dir="./data",
        yaml_file="drive_audit.yml",
        files_csv="files.csv",
        permissions_csv="permissions.csv",
        list_folder_children_cache_timeout=3600,
    )


def _file_info():
    permission_details = [
        PermissionDetails(
            permission_type="user", role="writer", inherited=False, inherited_from=None
        )
    ]
    permission = Permission(
        id="perm1",
        type="user",
        role="owner",
        email="owner@example.com",
        domain=None,
        display_name="Owner",
        allow_file_discovery=None,
        expiration=None,
        deleted=False,
        permission_details=permission_details,
    )

    access = AccessInfo(
        inherited=False,
        inherited_from_id=None,
        inherited_from_name=None,
        inherited_from_location=None,
        general_access="restricted",
        general_role=None,
        general_domain=None,
        allow_file_discovery=None,
        has_link_sharing=False,
        permissions=[permission],
    )

    policy = PolicyInfo(
        is_under_public_folder=False,
        is_public_anyone=False,
        is_public_by_domain=False,
        public_outside_public_folder=False,
        notes=["reviewed"],
    )

    return FileInfo(
        id="file1",
        name="Doc",
        type="file",
        mime_type="text/plain",
        parents=[{"id": "root123", "name": "Root", "type": "folder"}],
        created=datetime(2024, 1, 1),
        modified=datetime(2024, 1, 2),
        viewed=datetime(2024, 1, 3),
        trashed=False,
        starred=False,
        size_bytes=100,
        owners=[{"emailAddress": "owner@example.com", "displayName": "Owner"}],
        last_modifying_user={
            "emailAddress": "editor@example.com",
            "displayName": "Editor",
        },
        client_id="client-1",
        client_name="Client One",
        location="Client One/Doc",
        depth=1,
        is_shortcut=False,
        shortcut_target_id=None,
        shortcut_target_type=None,
        shortcut_target_mime_type=None,
        access=access,
        policy=policy,
    )


def test_format_datetime_handles_none():
    assert format_datetime(None) is None


def test_save_yaml_writes_expected_structure(tmp_path):
    config = _config()
    file_info = _file_info()

    output_path = tmp_path / "drive.yml"
    save_yaml([file_info], config, output_path)

    with output_path.open() as f:
        data = yaml.safe_load(f)

    assert data["version"] == 1
    assert data["drive"]["id"] == "drive123"
    assert data["config"]["max_depth"] == 5
    assert data["documents"][0]["name"] == "Doc"
    assert data["documents"][0]["access"]["permissions"][0]["id"] == "perm1"
    assert data["documents"][0]["policy"]["notes"] == ["reviewed"]
