import csv
from datetime import datetime
from typing import Dict, List

from .model import FileInfo


def format_datetime(dt: datetime) -> str:
    """Format datetime for CSV export."""
    if dt is None:
        return ""
    return dt.isoformat()


def format_bool(value: bool) -> str:
    """Format boolean for CSV export."""
    if value is None:
        return ""
    return str(value)


def save_files_csv(files: List[FileInfo], output_path: str):
    """Exports flat file list to CSV."""
    fieldnames = [
        "file_id",
        "name",
        "type",
        "mime_type",
        "client_name",
        "location",
        "depth",
        "is_shortcut",
        "shortcut_target_id",
        "created",
        "modified",
        "viewed",
        "owner_email",
        "last_modifying_user_email",
        "size_bytes",
        "general_access",
        "general_role",
        "general_domain",
        "general_has_link_sharing",
        "policy_is_under_public_folder",
        "policy_is_public_anyone",
        "policy_is_public_by_domain",
        "policy_public_outside_public_folder",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for file_info in files:
            row = {
                "file_id": file_info.id,
                "name": file_info.name,
                "type": file_info.type,
                "mime_type": file_info.mime_type,
                "client_name": file_info.client_name,
                "location": file_info.location,
                "depth": file_info.depth,
                "is_shortcut": format_bool(file_info.is_shortcut),
                "shortcut_target_id": file_info.shortcut_target_id or "",
                "created": format_datetime(file_info.created),
                "modified": format_datetime(file_info.modified),
                "viewed": format_datetime(file_info.viewed),
                "owner_email": (
                    file_info.owners[0].get("emailAddress") if file_info.owners else ""
                ),
                "last_modifying_user_email": (
                    file_info.last_modifying_user.get("emailAddress")
                    if file_info.last_modifying_user
                    else ""
                ),
                "size_bytes": (
                    file_info.size_bytes if file_info.size_bytes is not None else ""
                ),
                "general_access": file_info.access.general_access,
                "general_role": file_info.access.general_role or "",
                "general_domain": file_info.access.general_domain or "",
                "general_has_link_sharing": format_bool(
                    file_info.access.has_link_sharing
                ),
                "policy_is_under_public_folder": format_bool(
                    file_info.policy.is_under_public_folder
                ),
                "policy_is_public_anyone": format_bool(
                    file_info.policy.is_public_anyone
                ),
                "policy_is_public_by_domain": format_bool(
                    file_info.policy.is_public_by_domain
                ),
                "policy_public_outside_public_folder": format_bool(
                    file_info.policy.public_outside_public_folder
                ),
            }
            writer.writerow(row)


def save_permissions_csv(files: List[FileInfo], output_path: str):
    """Exports detailed permissions list to CSV."""
    fieldnames = [
        "file_id",
        "file_name",
        "location",
        "client_name",
        "permission_id",
        "permission_type",
        "permission_role",
        "permission_email",
        "permission_domain",
        "display_name",
        "allow_file_discovery",
        "expiration",
        "deleted",
        "inherited",
        "inherited_from_id",
        "inherited_from_location",
    ]

    # Build a map of file_id -> location for inherited_from_location lookup
    file_location_map: Dict[str, str] = {
        file_info.id: file_info.location for file_info in files
    }

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for file_info in files:
            for p in file_info.access.permissions:
                # Calculate aggregated inherited status
                inherited = None
                if p.permission_details:
                    # Logic: True if all are true, False if any is false
                    all_true = True
                    for d in p.permission_details:
                        if not d.inherited:
                            all_true = False
                            break
                    inherited = all_true

                inherited_from_id = None
                for d in p.permission_details:
                    if d.inherited_from:
                        inherited_from_id = d.inherited_from
                        break

                # Look up inherited_from_location
                inherited_from_location = ""
                if inherited_from_id and inherited_from_id in file_location_map:
                    inherited_from_location = file_location_map[inherited_from_id]

                row = {
                    "file_id": file_info.id,
                    "file_name": file_info.name,
                    "location": file_info.location,
                    "client_name": file_info.client_name,
                    "permission_id": p.id,
                    "permission_type": p.type,
                    "permission_role": p.role,
                    "permission_email": p.email or "",
                    "permission_domain": p.domain or "",
                    "display_name": p.display_name or "",
                    "allow_file_discovery": format_bool(p.allow_file_discovery),
                    "expiration": format_datetime(p.expiration),
                    "deleted": format_bool(p.deleted),
                    "inherited": format_bool(inherited),
                    "inherited_from_id": inherited_from_id or "",
                    "inherited_from_location": inherited_from_location,
                }
                writer.writerow(row)
