from datetime import datetime
from typing import Any, Dict, List

import yaml

from .model import DriveConfig, FileInfo


def format_datetime(dt: datetime) -> str:
    if not dt:
        return None
    return dt.isoformat()


def save_yaml(files: List[FileInfo], config: DriveConfig, output_path: str):
    """
    Exports the file structure and permissions to a YAML file.
    """

    # Prepare the data structure
    data = {
        "version": 1,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "drive": {
            "id": config.drive_id,
            "name": "Shared Drive",  # We might want to fetch this if possible, but for now placeholder or config
            "root_folder_id": config.root_folder_id,
            "root_folder_name": config.root_folder_name,
        },
        "config": {
            "include_trashed": config.include_trashed,
            "include_shortcuts": config.include_shortcuts,
            "public_subdir": config.public_subdir,
            "max_depth": config.max_depth,
        },
        "documents": [],
    }

    for f in files:
        doc = {
            "id": f.id,
            "name": f.name,
            "type": f.type,
            "mime_type": f.mime_type,
            "client": {"id": f.client_id, "name": f.client_name},
            "location": f.location,
            "depth": f.depth,
            "parents": [
                {"id": p, "name": "Unknown", "type": "folder"} for p in f.parents
            ],  # Name lookup would require map
            "shortcut": {
                "is_shortcut": f.is_shortcut,
                "target_id": f.shortcut_target_id,
                "target_type": f.shortcut_target_type,
                "target_mime_type": f.shortcut_target_mime_type,
            },
            "created": format_datetime(f.created),
            "modified": format_datetime(f.modified),
            "viewed": format_datetime(f.viewed),
            "trashed": f.trashed,
            "starred": f.starred,
            "size_bytes": f.size_bytes,
            "owners": [
                {
                    "email": o.get("emailAddress") if isinstance(o, dict) else None,
                    "display_name": (
                        o.get("displayName") if isinstance(o, dict) else None
                    ),
                }
                for o in (f.owners or [])
            ],
            "last_modifying_user": {
                "email": (
                    f.last_modifying_user.get("emailAddress")
                    if f.last_modifying_user
                    else None
                ),
                "display_name": (
                    f.last_modifying_user.get("displayName")
                    if f.last_modifying_user
                    else None
                ),
            },
            "access": {
                "inherited": f.access.inherited,
                "inherited_from": {
                    "id": f.access.inherited_from_id,
                    "name": f.access.inherited_from_name,
                    "location": f.access.inherited_from_location,
                },
                "general": {
                    "access": f.access.general_access,
                    "role": f.access.general_role,
                    "domain": f.access.general_domain,
                    "allow_file_discovery": f.access.allow_file_discovery,
                    "has_link_sharing": f.access.has_link_sharing,
                },
                "permissions": [],
            },
            "policy": {
                "is_under_public_folder": f.policy.is_under_public_folder,
                "is_public_anyone": f.policy.is_public_anyone,
                "is_public_by_domain": f.policy.is_public_by_domain,
                "public_outside_public_folder": f.policy.public_outside_public_folder,
                "notes": f.policy.notes,
            },
        }

        for p in f.access.permissions:
            perm_doc = {
                "id": p.id,
                "type": p.type,
                "role": p.role,
                "email": p.email,
                "domain": p.domain,
                "display_name": p.display_name,
                "allow_file_discovery": p.allow_file_discovery,
                "expiration": format_datetime(p.expiration),
                "deleted": p.deleted,
                "permission_details": [],
            }
            for d in p.permission_details:
                perm_doc["permission_details"].append(
                    {
                        "permission_type": d.permission_type,
                        "role": d.role,
                        "inherited": d.inherited,
                        "inherited_from": d.inherited_from,
                    }
                )
            doc["access"]["permissions"].append(perm_doc)

        data["documents"].append(doc)

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
