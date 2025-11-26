import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .model import AccessInfo, DriveConfig, FileInfo, Permission, PermissionDetails
from .policy import check_policy

logger = logging.getLogger(__name__)


def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        # Google Drive API returns ISO 8601 strings like '2023-10-26T12:00:00.000Z'
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_file_tree(
    files_data: List[Dict[str, Any]], config: DriveConfig
) -> List[FileInfo]:
    """
    Processes raw file data into a list of FileInfo objects with resolved paths and policies.
    """

    # 1. Create a map for quick lookup
    file_map = {f["id"]: f for f in files_data}

    # Log configuration for debugging
    if config.root_folder_id == config.drive_id:
        logger.debug(
            f"Scanning entire drive (root_folder_id == drive_id: {config.drive_id})"
        )
    else:
        logger.debug(f"Scanning from root folder: {config.root_folder_id}")

    # 2. Process each file
    processed_files = []

    for file_data in files_data:
        file_id = file_data.get("id")
        name = file_data.get("name")
        mime_type = file_data.get("mimeType")

        # Resolve Path
        path_segments = []
        current_id = file_id
        valid_path = True

        # Special case: if root_folder_id equals drive_id, we're scanning the entire drive
        # In Shared Drives, files don't have the drive_id as a parent - they have folder IDs
        # So we skip the parent chain check and include all files
        if config.root_folder_id == config.drive_id:
            # Scan everything in the drive - no filtering needed
            temp_chain = []
            curr = file_data
            while True:
                temp_chain.append(curr.get("name"))
                parents = curr.get("parents", [])
                if not parents:
                    # Reached a root or orphan - this is fine for drive-wide scan
                    break
                parent_id = parents[0]
                if parent_id not in file_map:
                    # Parent not in our list - stop here
                    break
                curr = file_map[parent_id]
        else:
            # We need to traverse up to the root_folder_id
            # Note: This simple traversal assumes one parent.
            # Shared Drives usually enforce single parent structure, but API allows multiple.
            # We'll take the first parent for simplicity as per standard Shared Drive behavior.

            temp_chain = []

            # Start climbing from the file itself
            curr = file_data
            while True:
                temp_chain.append(curr.get("name"))

                parents = curr.get("parents", [])
                if not parents:
                    # Reached a root or orphan
                    # If we hit the config.root_folder_id, we are good.
                    # But wait, the loop logic needs to check parent ID.
                    break

                parent_id = parents[0]

                if parent_id == config.root_folder_id:
                    # We found the root.
                    # The root folder name itself is usually not part of the path in terms of "Client/..."
                    # if "Client" is a child of Root.
                    # But requirements say: "root_folder_name" is "Clients".
                    # And location: "/Client/public/file.ext"
                    # So if Root is "Clients", and file is in "ClientA", path is "/ClientA/..."
                    break

                if parent_id not in file_map:
                    # Parent not found in our list (maybe outside scope or we don't have access)
                    valid_path = False
                    break

                curr = file_map[parent_id]

            if not valid_path:
                # Skip files not rooted in our target folder
                logger.debug(
                    f"Skipping file {file_data.get('name')} (id: {file_id}) - not under root_folder_id {config.root_folder_id}"
                )
                continue

        # Reverse the chain to get path
        # temp_chain has [File, Parent, Grandparent...]
        # We stopped BEFORE adding Root.
        # So path is reversed temp_chain.
        path_segments = list(reversed(temp_chain))

        # Location string
        location = "/" + "/".join(path_segments)

        # Depth
        depth = len(path_segments)

        # Client
        # First segment is client
        client_name = path_segments[0] if path_segments else None
        client_id = None  # We'd need to track IDs in the chain to get this, skipping for now unless critical

        # Parse Permissions
        permissions_data = file_data.get("permissions", [])
        permissions = []

        has_anyone = False
        has_domain = False

        for p in permissions_data:
            p_details = []
            for d in p.get("permissionDetails", []):
                p_details.append(
                    PermissionDetails(
                        permission_type=d.get("permissionType", ""),
                        role=d.get("role", ""),
                        inherited=d.get("inherited", False),
                        inherited_from=d.get("inheritedFrom"),
                    )
                )

            perm = Permission(
                id=p.get("id"),
                type=p.get("type"),
                role=p.get("role"),
                email=p.get("emailAddress"),
                domain=p.get("domain"),
                display_name=p.get("displayName"),
                allow_file_discovery=p.get("allowFileDiscovery"),
                expiration=parse_datetime(p.get("expirationTime")),
                deleted=p.get("deleted"),
                permission_details=p_details,
            )
            permissions.append(perm)

            if perm.type == "anyone":
                has_anyone = True
            if perm.type == "domain":
                has_domain = True

        # General Access Logic
        general_access = "restricted"
        general_role = None
        general_domain = None
        allow_file_discovery = None

        if has_anyone:
            general_access = "anyone"
            # Find the anyone permission to get role
            for p in permissions:
                if p.type == "anyone":
                    general_role = p.role
                    allow_file_discovery = p.allow_file_discovery
                    break
        elif has_domain:
            general_access = "domain"
            for p in permissions:
                if p.type == "domain":
                    general_role = p.role
                    general_domain = p.domain
                    allow_file_discovery = p.allow_file_discovery
                    break

        # Inherited logic
        # "True, если все permissionDetails по всем permissions inherited = True"
        all_inherited = True
        if not permissions:
            all_inherited = False  # No permissions means not inherited? Or N/A? Assuming False for now.
        else:
            for p in permissions:
                # If any permission has NO details, is it inherited? Usually explicit.
                if not p.permission_details:
                    all_inherited = False
                    break
                for d in p.permission_details:
                    if not d.inherited:
                        all_inherited = False
                        break
                if not all_inherited:
                    break

        inherited_from_id = None
        # Just grab the first one found
        for p in permissions:
            for d in p.permission_details:
                if d.inherited_from:
                    inherited_from_id = d.inherited_from
                    break
            if inherited_from_id:
                break

        access_info = AccessInfo(
            inherited=all_inherited,
            inherited_from_id=inherited_from_id,
            inherited_from_name=None,  # Would need lookup
            inherited_from_location=None,  # Would need lookup
            general_access=general_access,
            general_role=general_role,
            general_domain=general_domain,
            allow_file_discovery=allow_file_discovery,
            has_link_sharing=has_anyone,
            permissions=permissions,
        )

        # Shortcut handling
        is_shortcut = mime_type == "application/vnd.google-apps.shortcut"
        shortcut_details = file_data.get("shortcutDetails", {})

        # For Shared Drives, owners field is often empty
        # Fallback: derive owners from permissions with organizer/owner role
        owners = file_data.get("owners", [])
        if not owners and permissions:
            # Find permissions with organizer or owner role
            for perm in permissions:
                if (
                    perm.role in ["organizer", "owner"]
                    and perm.type == "user"
                    and perm.email
                ):
                    owners.append(
                        {
                            "emailAddress": perm.email,
                            "displayName": perm.display_name or perm.email,
                        }
                    )

        file_info = FileInfo(
            id=file_id,
            name=name,
            type=(
                "shortcut"
                if is_shortcut
                else (
                    "folder"
                    if mime_type == "application/vnd.google-apps.folder"
                    else "file"
                )
            ),
            mime_type=mime_type,
            parents=file_data.get("parents", []),
            created=parse_datetime(file_data.get("createdTime")),
            modified=parse_datetime(file_data.get("modifiedTime")),
            viewed=parse_datetime(file_data.get("viewedByMeTime")),
            trashed=file_data.get("trashed", False),
            starred=file_data.get("starred", False),
            size_bytes=int(file_data.get("size")) if file_data.get("size") else None,
            owners=owners,
            last_modifying_user=file_data.get("lastModifyingUser"),
            client_name=client_name,
            location=location,
            depth=depth,
            is_shortcut=is_shortcut,
            shortcut_target_id=shortcut_details.get("targetId"),
            shortcut_target_mime_type=shortcut_details.get("targetMimeType"),
            shortcut_target_type=(
                "folder"
                if shortcut_details.get("targetMimeType")
                == "application/vnd.google-apps.folder"
                else ("file" if shortcut_details.get("targetId") else None)
            ),
            access=access_info,
        )

        # Apply Policy
        file_info.policy = check_policy(file_info, config)

        processed_files.append(file_info)

    return processed_files
