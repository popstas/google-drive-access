import re
from typing import Any, Dict, Iterable, List, Set, Tuple

from loguru import logger

from .google_client import ensure_public_subdir, list_folder_children, move_file
from .model import DriveConfig


def validate_public_folder_move_inputs(
    drive_config: DriveConfig, file_matches: Any, mime_type_matches: Any
) -> Tuple[List[re.Pattern[str]], Set[str]]:
    """Validate inputs for moving files to public folders.

    Returns compiled regex patterns and a set of allowed mime types (lowercased).
    """

    if not drive_config.public_subdir:
        raise ValueError(
            "public_subdir must be configured to move files to a public folder"
        )

    if isinstance(file_matches, str):
        file_matches = [file_matches]
    if not isinstance(file_matches, list) or not file_matches:
        raise ValueError("file_matches must be a non-empty list of regex patterns")
    if not all(isinstance(pattern, str) for pattern in file_matches):
        raise ValueError("file_matches entries must be strings")

    patterns = [re.compile(pattern, re.IGNORECASE) for pattern in file_matches]

    mime_types: List[str] = []
    if mime_type_matches is not None:
        if isinstance(mime_type_matches, str):
            mime_types = [mime_type_matches]
        elif isinstance(mime_type_matches, list) and all(
            isinstance(mime, str) for mime in mime_type_matches
        ):
            mime_types = mime_type_matches
        else:
            raise ValueError("mime_type_matches must be a string or list of strings")

    allowed_mime_types = {mime.lower() for mime in mime_types if mime}

    logger.debug(
        "Validated inputs: {} filename patterns, {} mime types",
        len(patterns),
        len(allowed_mime_types) if allowed_mime_types else "any",
    )

    return patterns, allowed_mime_types


def collect_public_folder_matches(
    service,
    drive_config: DriveConfig,
    patterns: Iterable[re.Pattern[str]],
    allowed_mime_types: Iterable[str],
) -> List[Dict[str, Any]]:
    """Scan client folders for files that should be moved into public folders."""

    folder_mime = "application/vnd.google-apps.folder"
    matched_files: List[Dict[str, Any]] = []
    public_folders: Dict[str, Dict[str, Any]] = {}
    allowed_mime_types_set = set(allowed_mime_types)

    for client_folder in list_folder_children(
        service,
        drive_config.root_folder_id,
        drive_config.drive_id,
        cache_timeout_seconds=drive_config.list_folder_children_cache_timeout,
    ):
        client_name = client_folder.get("name", "")
        client_folder_id = client_folder.get("id")
        if client_folder.get("mimeType") != folder_mime or not client_folder_id:
            logger.debug(
                "Skipping non-folder item {} ({}) at root level",
                client_name,
                client_folder_id,
            )
            continue

        logger.debug("Scanning client folder {} ({})", client_name, client_folder_id)
        for file_data in list_folder_children(
            service,
            client_folder_id,
            drive_config.drive_id,
            cache_timeout_seconds=drive_config.list_folder_children_cache_timeout,
        ):
            name = file_data.get("name", "")
            mime_type = file_data.get("mimeType") or ""
            parents = file_data.get("parents", [])

            if mime_type == folder_mime:
                logger.debug(
                    "Skipping subfolder {} ({}) under {}",
                    name,
                    file_data.get("id"),
                    client_name,
                )
                continue

            if not any(pattern.search(name) for pattern in patterns):
                continue

            if (
                allowed_mime_types_set
                and mime_type.lower() not in allowed_mime_types_set
            ):
                continue

            public_folder = public_folders.get(client_folder_id)
            if not public_folder:
                public_folder = ensure_public_subdir(
                    service,
                    client_folder_id,
                    drive_config.public_subdir,
                    drive_config.drive_id,
                )
                public_folders[client_folder_id] = public_folder

            if public_folder["id"] in parents:
                logger.debug(
                    "File {} ({}) already in public folder", name, file_data.get("id")
                )
                continue

            matched_files.append(
                {
                    "file": file_data,
                    "public_folder": public_folder,
                    "client_name": client_name,
                }
            )

    logger.info("Collected {} files to move to public folders", len(matched_files))
    return matched_files


def execute_public_folder_moves(
    service,
    matches: List[Dict[str, Any]],
    drive_config: DriveConfig,
    dry_run: bool,
) -> List[Dict[str, Any]]:
    """Move matched files into their public folders or report what would happen."""

    moved_files: List[Dict[str, Any]] = []
    for match in matches:
        file_data = match["file"]
        public_folder = match["public_folder"]
        file_id = file_data.get("id")
        if not file_id:
            logger.debug("Skipping file without id: {}", file_data)
            continue

        parents = file_data.get("parents", [])
        if not parents:
            logger.warning(
                "File {} ({}) has no parents; skipping", file_data.get("name"), file_id
            )
            continue

        destination_parent = public_folder["id"]
        destination_path = f"{match['client_name']}/{public_folder.get('name', drive_config.public_subdir)}"

        if dry_run:
            logger.info(
                "[dry-run] Would move {} ({}) from {} to {} ({})",
                file_data.get("name"),
                file_id,
                ",".join(parents),
                destination_parent,
                destination_path,
            )
            moved_files.append(
                {
                    "file_id": file_id,
                    "new_parent": destination_parent,
                    "destination_path": destination_path,
                    "dry_run": True,
                }
            )
            continue

        updated = move_file(
            service, file_id, destination_parent, parents, drive_config.drive_id
        )
        updated["destination_path"] = destination_path
        moved_files.append(updated)
        logger.info(
            "Moved {} ({}) from {} to {} ({})",
            file_data.get("name"),
            file_id,
            ",".join(parents),
            destination_parent,
            destination_path,
        )

    return moved_files
