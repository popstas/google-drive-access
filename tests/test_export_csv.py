import csv
from datetime import datetime

from drive_audit.export_csv import (
    format_bool,
    format_datetime,
    save_files_csv,
    save_permissions_csv,
)
from drive_audit.model import (
    AccessInfo,
    FileInfo,
    Permission,
    PermissionDetails,
    PolicyInfo,
)


def _build_file_info(**kwargs):
    defaults = {
        "id": "file1",
        "name": "Document",
        "type": "file",
        "mime_type": "text/plain",
        "parents": [],
        "created": datetime(2024, 1, 1),
        "modified": datetime(2024, 1, 2),
        "viewed": None,
        "trashed": False,
        "starred": False,
        "size_bytes": 123,
        "owners": [{"emailAddress": "owner@example.com"}],
        "last_modifying_user": {"emailAddress": "owner@example.com"},
        "client_id": "client-1",
        "client_name": "Client One",
        "location": "Client One/Document",
        "depth": 1,
        "is_shortcut": False,
        "shortcut_target_id": None,
        "shortcut_target_type": None,
        "shortcut_target_mime_type": None,
        "access": AccessInfo(
            inherited=True,
            inherited_from_id=None,
            inherited_from_name=None,
            inherited_from_location=None,
            general_access="domain",
            general_role="reader",
            general_domain="example.com",
            allow_file_discovery=True,
            has_link_sharing=False,
            permissions=[],
        ),
        "policy": PolicyInfo(
            is_under_public_folder=False,
            is_public_anyone=False,
            is_public_by_domain=False,
            public_outside_public_folder=False,
            notes=[],
        ),
    }
    defaults.update(kwargs)
    return FileInfo(**defaults)


def test_format_helpers_handle_none():
    assert format_datetime(None) == ""
    assert format_bool(None) == ""


def test_save_files_csv_writes_expected_rows(tmp_path):
    files = [
        _build_file_info(),
        _build_file_info(
            id="shortcut1",
            name="Shortcut",
            type="shortcut",
            is_shortcut=True,
            shortcut_target_id="target123",
            shortcut_target_type="file",
            shortcut_target_mime_type="application/pdf",
            access=AccessInfo(
                inherited=False,
                inherited_from_id="folder-2",
                inherited_from_name="Folder 2",
                inherited_from_location="Client One/Folder 2",
                general_access="anyone",
                general_role=None,
                general_domain=None,
                allow_file_discovery=None,
                has_link_sharing=True,
                permissions=[],
            ),
            policy=PolicyInfo(
                is_under_public_folder=True,
                is_public_anyone=True,
                is_public_by_domain=False,
                public_outside_public_folder=True,
                notes=["outside"],
            ),
        ),
    ]

    output_path = tmp_path / "files.csv"
    save_files_csv(files, output_path)

    with output_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert rows[0]["file_id"] == "file1"
    assert rows[0]["general_access"] == "domain"
    assert rows[1]["is_shortcut"] == "True"
    assert rows[1]["shortcut_target_id"] == "target123"
    assert rows[1]["policy_is_public_anyone"] == "True"


def test_save_permissions_csv_includes_inherited_details(tmp_path):
    parent_file = _build_file_info(id="parent", location="Parent")
    permission_details = [
        PermissionDetails(
            permission_type="user",
            role="writer",
            inherited=True,
            inherited_from="parent",
        ),
        PermissionDetails(
            permission_type="user",
            role="reader",
            inherited=True,
            inherited_from="parent",
        ),
    ]
    permission = Permission(
        id="perm1",
        type="user",
        role="reader",
        email="collab@example.com",
        domain=None,
        display_name="Collaborator",
        allow_file_discovery=False,
        expiration=datetime(2024, 2, 1),
        deleted=False,
        permission_details=permission_details,
    )
    child_file = _build_file_info(
        id="child",
        location="Parent/Child",
        access=AccessInfo(
            inherited=True,
            inherited_from_id="parent",
            inherited_from_name="Parent",
            inherited_from_location="Parent",
            general_access="restricted",
            general_role=None,
            general_domain=None,
            allow_file_discovery=None,
            has_link_sharing=False,
            permissions=[permission],
        ),
    )

    output_path = tmp_path / "permissions.csv"
    save_permissions_csv([parent_file, child_file], output_path)

    with output_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert rows[0]["permission_id"] == "perm1"
    assert rows[0]["inherited"] == "True"
    assert rows[0]["inherited_from_location"] == "Parent"
