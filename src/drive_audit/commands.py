import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from unicodedata import normalize

from loguru import logger

from .compare import compare_files_by_location
from .config_loader import build_planfix_config
from .google_client import (
    create_folder,
    delete_folder,
    find_child_folder,
    get_file_permissions,
    get_service,
    list_folder_children,
    move_file,
)
from .logger_config import configure_logger
from .main import load_config
from .model import DriveConfig
from .planfix_client import PlanfixClient
from .public_folder_ops import (
    collect_public_folder_matches,
    execute_public_folder_moves,
    validate_public_folder_move_inputs,
)


def move_files_to_public_folder(
    service,
    drive_config: DriveConfig,
    file_matches: Any,
    dry_run: bool,
    mime_type_matches: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    patterns, allowed_mime_types = validate_public_folder_move_inputs(
        drive_config, file_matches, mime_type_matches
    )

    matches = collect_public_folder_matches(
        service, drive_config, patterns, allowed_mime_types
    )

    return execute_public_folder_moves(service, matches, drive_config, dry_run)


def move_files_from_csv(
    service, drive_config: DriveConfig, csv_file: Path, dry_run: bool
) -> List[Dict[str, Any]]:
    csv_path = Path(csv_file)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    if not csv_path.is_file():
        raise ValueError(f"CSV path must be a file: {csv_path}")

    move_rows = []
    with csv_path.open(encoding="utf-8-sig", newline="") as csv_handle:
        reader = csv.DictReader(csv_handle)
        required_headers = {"file_name", "file_id", "dest_folder"}
        if not reader.fieldnames or not required_headers.issubset(
            set(reader.fieldnames)
        ):
            raise ValueError(
                f"CSV must contain headers {sorted(required_headers)}, got {reader.fieldnames}"
            )

        for index, row in enumerate(reader, start=2):
            file_name = (row.get("file_name") or "").strip()
            file_id = (row.get("file_id") or "").strip()
            dest_folder_id = (row.get("dest_folder") or "").strip()
            source_folder_id = (row.get("source_folder") or "").strip()

            if not file_name and not file_id:
                continue
            if file_name.startswith("#"):
                continue

            if not file_id or not dest_folder_id:
                logger.warning(
                    "Row {} is missing file_id or dest_folder; skipping entry '{}'",
                    index,
                    file_name or row,
                )
                continue

            move_rows.append(
                {
                    "name": file_name,
                    "file_id": file_id,
                    "dest_folder_id": dest_folder_id,
                    "source_folder_id": source_folder_id,
                }
            )

    if not move_rows:
        logger.info("No actionable rows detected in {}", csv_path)
        return []

    moved_files: List[Dict[str, Any]] = []
    files_resource = service.files()

    for row in move_rows:
        file_id = row["file_id"]
        destination_parent = row["dest_folder_id"]
        file_metadata = files_resource.get(
            fileId=file_id,
            fields="id,name,parents",
            supportsAllDrives=True,
        ).execute()

        parents = file_metadata.get("parents", [])
        if not parents:
            logger.warning(
                "File {} ({}) has no parents; skipping",
                file_metadata.get("name"),
                file_id,
            )
            continue

        file_name = file_metadata.get("name") or row["name"]

        if destination_parent in parents:
            logger.info(
                "File {} ({}) already resides in destination {}",
                file_name,
                file_id,
                destination_parent,
            )
            continue

        if dry_run:
            logger.info(
                "[dry-run] Would move {} ({}) from {} to {}",
                file_name,
                file_id,
                ",".join(parents),
                destination_parent,
            )
            moved_files.append(
                {
                    "file_id": file_id,
                    "new_parent": destination_parent,
                    "dry_run": True,
                }
            )
            continue

        updated = move_file(
            service, file_id, destination_parent, parents, drive_config.drive_id
        )
        updated["destination_parent"] = destination_parent
        moved_files.append(updated)
        logger.info(
            "Moved {} ({}) from {} to {}",
            file_name,
            file_id,
            ",".join(parents),
            destination_parent,
        )

    return moved_files


def recheck_files_from_drive(
    service,
    drive_config: DriveConfig,
    csv_file: Optional[Path] = None,
    file_ids: Optional[List[str]] = None,
    output_path: Path = Path("data/recheck_results.csv"),
) -> None:
    """
    Recheck files from Google Drive by file_id or location from CSV.
    Fetches current file metadata and writes to output CSV.
    """
    file_ids_to_check: List[str] = []

    if file_ids:
        file_ids_to_check.extend(file_ids)

    if csv_file:
        if not csv_file.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_file}")

        with csv_file.open(encoding="utf-8-sig", newline="") as csv_handle:
            reader = csv.DictReader(csv_handle)
            if not reader.fieldnames:
                raise ValueError(f"CSV file {csv_file} has no headers")

            for row in reader:
                file_id = (row.get("file_id") or "").strip()
                if file_id:
                    file_ids_to_check.append(file_id)

    if not file_ids_to_check:
        logger.warning("No file IDs to recheck")
        return

    logger.info("Rechecking {} files from Google Drive", len(file_ids_to_check))

    files_resource = service.files()
    recheck_results: List[Dict[str, Any]] = []

    fields = "id,name,mimeType,parents,createdTime,modifiedTime,viewedByMeTime,owners,lastModifyingUser,trashed,starred,size,shortcutDetails"

    for idx, file_id in enumerate(file_ids_to_check, 1):
        try:
            file_metadata = files_resource.get(
                fileId=file_id,
                fields=fields,
                supportsAllDrives=True,
            ).execute()

            # Get permissions
            try:
                permissions = get_file_permissions(service, file_id)
            except Exception as e:
                logger.warning("Failed to get permissions for {}: {}", file_id, e)
                permissions = []

            result_row = {
                "file_id": file_metadata.get("id", ""),
                "name": file_metadata.get("name", ""),
                "mime_type": file_metadata.get("mimeType", ""),
                "parents": ",".join(file_metadata.get("parents", [])),
                "created": file_metadata.get("createdTime", ""),
                "modified": file_metadata.get("modifiedTime", ""),
                "viewed": file_metadata.get("viewedByMeTime", ""),
                "trashed": str(file_metadata.get("trashed", False)),
                "starred": str(file_metadata.get("starred", False)),
                "size_bytes": str(file_metadata.get("size", "")),
                "owner_emails": ",".join(
                    owner.get("emailAddress", "")
                    for owner in file_metadata.get("owners", [])
                ),
                "last_modifying_user_email": (
                    file_metadata.get("lastModifyingUser", {}).get("emailAddress", "")
                ),
                "permissions_count": str(len(permissions)),
                "shortcut_target_id": (
                    file_metadata.get("shortcutDetails", {}).get("targetId", "")
                ),
            }
            recheck_results.append(result_row)

            if idx % 10 == 0:
                logger.debug("Rechecked {}/{} files", idx, len(file_ids_to_check))

        except Exception as e:
            logger.error("Failed to recheck file {}: {}", file_id, e)
            recheck_results.append(
                {
                    "file_id": file_id,
                    "error": str(e),
                }
            )

    # Write results
    if recheck_results:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(recheck_results[0].keys())
        with output_path.open("w", newline="", encoding="utf-8") as csv_handle:
            writer = csv.DictWriter(csv_handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in recheck_results:
                writer.writerow(row)

        logger.info(
            "Wrote {} recheck results to {}",
            len(recheck_results),
            output_path,
        )
    else:
        logger.warning("No results to write")


def _get_relative_path_from_csv(
    file_id: str,
    source_folder_id: str,
    all_rows: List[Dict[str, Any]],
) -> List[str]:
    """
    Get relative path from source_folder_id to file's parent folder from CSV.
    Returns list of folder names in the path.
    """
    # Find file in CSV
    file_row = None
    for row in all_rows:
        if row.get("file_id", "").strip() == file_id:
            file_row = row
            break

    if not file_row:
        return []

    file_location = file_row.get("location", "").strip()
    if not file_location:
        return []

    # Find source folder in CSV
    source_folder_row = None
    for row in all_rows:
        if row.get("file_id", "").strip() == source_folder_id:
            source_folder_row = row
            break

    if not source_folder_row:
        return []

    source_folder_location = source_folder_row.get("location", "").strip()
    if not source_folder_location:
        return []

    # Normalize locations (remove trailing slashes)
    file_location = file_location.rstrip("/")
    source_folder_location = source_folder_location.rstrip("/")

    # Check if file is under source folder
    if not file_location.startswith(source_folder_location):
        return []

    # Get relative path
    relative_path = file_location[len(source_folder_location) :].lstrip("/")

    # Remove filename from path (last segment)
    path_parts = relative_path.split("/")
    if len(path_parts) > 1:
        # Return folder names (all except the last one which is the filename)
        return path_parts[:-1]
    else:
        # File is directly in source folder
        return []


def _ensure_folder_structure(
    service,
    base_folder_id: str,
    folder_path: List[str],
    drive_id: str,
    dry_run: bool = False,
) -> str:
    """
    Ensure folder structure exists under base_folder_id.
    Creates folders if they don't exist.
    Returns the ID of the final folder in the path.
    """
    current_folder_id = base_folder_id

    for folder_name in folder_path:
        if not folder_name:
            continue

        # Try to find existing folder
        existing_folder = find_child_folder(
            service,
            current_folder_id,
            folder_name,
            drive_id,
        )

        if existing_folder:
            current_folder_id = existing_folder["id"]
        else:
            # Create folder
            if dry_run:
                logger.debug(
                    "    [dry-run] Would create folder '{}' under {}",
                    folder_name,
                    current_folder_id,
                )
                # For dry-run, we can't create the folder, so we'll use base_folder_id
                # This is not perfect, but it's acceptable for dry-run
                # We'll still return base_folder_id to indicate where it would be moved
                break
            else:
                new_folder = create_folder(
                    service,
                    current_folder_id,
                    folder_name,
                    drive_id,
                )
                current_folder_id = new_folder["id"]
                logger.debug(
                    "    Created folder '{}' ({}) under {}",
                    folder_name,
                    current_folder_id,
                    current_folder_id,
                )

    return current_folder_id


def merge_client_folders(
    service,
    drive_config: DriveConfig,
    csv_file: Path = Path("data/new_disk/new_files.csv"),
    dry_run: bool = False,
    output_csv: Path = Path("data/merge_client_folders.csv"),
) -> None:
    """
    Merge duplicate folders at depth=1 by moving all files from duplicates into the first folder,
    then deleting empty duplicate folders.

    Args:
        service: Google Drive service object
        drive_config: Drive configuration
        csv_file: Path to CSV file with full file structure
        dry_run: If True, only log actions without executing
        output_csv: Path to output CSV file for logging operations
    """
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    logger.info("Reading CSV file from {}", csv_file)

    # Read all rows from CSV
    all_rows: List[Dict[str, Any]] = []
    with csv_file.open(encoding="utf-8-sig", newline="") as csv_handle:
        reader = csv.DictReader(csv_handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV file {csv_file} has no headers")

        for row in reader:
            all_rows.append(row)

    logger.info("Read {} rows from CSV", len(all_rows))

    # Filter folders at depth=1
    depth_1_folders = [
        row
        for row in all_rows
        if row.get("type") == "folder" and row.get("depth") == "1"
    ]

    logger.info("Found {} folders at depth=1", len(depth_1_folders))

    # Group folders by normalized name
    folders_by_name: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for folder in depth_1_folders:
        folder_name = folder.get("name", "").strip()
        normalized_name = normalize("NFC", folder_name)
        folders_by_name[normalized_name].append(folder)

    # Find duplicates (folders with same normalized name)
    duplicate_groups = {
        name: folders for name, folders in folders_by_name.items() if len(folders) > 1
    }

    if not duplicate_groups:
        logger.info("No duplicate folders found at depth=1")
        return

    logger.info("Found {} duplicate folder groups", len(duplicate_groups))

    # Prepare output CSV
    output_rows: List[Dict[str, Any]] = []
    files_resource = service.files()

    # Process each duplicate group
    for normalized_name, folders in duplicate_groups.items():
        # Sort folders by file_id (or created date) to keep the first one
        folders.sort(key=lambda f: (f.get("created", ""), f.get("file_id", "")))
        first_folder = folders[0]
        duplicate_folders = folders[1:]

        first_folder_id = first_folder.get("file_id")
        first_folder_name = first_folder.get("name", "")
        first_folder_location = first_folder.get("location", "")

        logger.info(
            "Processing duplicate group '{}': keeping first folder {} ({})",
            normalized_name,
            first_folder_name,
            first_folder_id,
        )
        logger.info(
            "  Will merge {} duplicate folders into it",
            len(duplicate_folders),
        )

        # Process each duplicate folder
        for dup_folder in duplicate_folders:
            dup_folder_id = dup_folder.get("file_id")
            dup_folder_name = dup_folder.get("name", "")
            dup_folder_location = dup_folder.get("location", "")

            logger.info(
                "  Merging folder {} ({}) into {}",
                dup_folder_name,
                dup_folder_id,
                first_folder_id,
            )

            # Find all files that belong to this duplicate folder using Google Drive API
            # We need to recursively collect all files from the folder
            def collect_files_recursively(folder_id: str) -> List[Dict[str, Any]]:
                """Recursively collect all files from a folder."""
                files_list = []
                try:
                    items_count = 0
                    for item in list_folder_children(
                        service,
                        folder_id,
                        drive_config.drive_id,
                    ):
                        items_count += 1
                        item_id = item.get("id")
                        item_name = item.get("name", "")
                        item_mime = item.get("mimeType", "")

                        # If it's a folder, recurse into it
                        if item_mime == "application/vnd.google-apps.folder":
                            logger.debug(
                                "    Found subfolder {} ({}) in {}",
                                item_name,
                                item_id,
                                folder_id,
                            )
                            files_list.extend(collect_files_recursively(item_id))
                        else:
                            # It's a file, add it to the list
                            logger.debug(
                                "    Found file {} ({}) in {}",
                                item_name,
                                item_id,
                                folder_id,
                            )
                            files_list.append(item)

                    if items_count == 0:
                        logger.debug(
                            "    No items found in folder {}",
                            folder_id,
                        )
                except Exception as e:
                    logger.error(
                        "    Failed to list children of folder {}: {}",
                        folder_id,
                        e,
                    )
                return files_list

            logger.info(
                "    Collecting files from folder {} ({})",
                dup_folder_name,
                dup_folder_id,
            )

            files_to_move = collect_files_recursively(dup_folder_id)

            # Also check CSV for files directly in the root of duplicate folder (depth=2)
            # This handles cases where API might not return files in root
            dup_folder_location = dup_folder.get("location", "").strip().rstrip("/")
            for row in all_rows:
                row_file_id = row.get("file_id", "").strip()
                row_location = row.get("location", "").strip().rstrip("/")
                row_type = row.get("type", "").strip().lower()
                row_depth = row.get("depth", "").strip()

                # Check if file is directly in duplicate folder (depth=2 and location matches)
                if (
                    row_type == "file"
                    and row_depth == "2"
                    and row_location.startswith(dup_folder_location + "/")
                    and row_location.count("/") == 2
                ):  # Exactly one level deeper

                    # Check if file is already in files_to_move
                    if not any(f.get("id") == row_file_id for f in files_to_move):
                        # File not found via API, add it from CSV
                        logger.debug(
                            "    Found file {} ({}) in CSV (depth=2, not found via API)",
                            row.get("name", ""),
                            row_file_id,
                        )
                        files_to_move.append(
                            {
                                "id": row_file_id,
                                "name": row.get("name", ""),
                                "mimeType": row.get("mime_type", ""),
                            }
                        )

            logger.info(
                "    Found {} files to move from {}",
                len(files_to_move),
                dup_folder_name,
            )

            # Move each file
            for file_item in files_to_move:
                file_id = file_item.get("id")
                file_name = file_item.get("name", "")

                if not file_id:
                    logger.warning("    Skipping file without id: {}", file_item)
                    continue

                # Get current parents from Google Drive (to verify and get full parent list)
                try:
                    file_metadata = files_resource.get(
                        fileId=file_id,
                        fields="id,name,parents",
                        supportsAllDrives=True,
                    ).execute()

                    current_parents = file_metadata.get("parents", [])
                    if not current_parents:
                        logger.warning(
                            "    File {} ({}) has no parents; skipping",
                            file_name,
                            file_id,
                        )
                        continue

                    # Check if file is already in the first folder
                    if first_folder_id in current_parents:
                        logger.debug(
                            "    File {} ({}) already in destination folder",
                            file_name,
                            file_id,
                        )
                        continue

                    # Note: We don't check if file is in dup_folder_id because
                    # files might be in subfolders of the duplicate folder.
                    # Since we collected them via list_folder_children recursively,
                    # we know they belong to the duplicate folder hierarchy.

                    # Get relative path from CSV to preserve folder structure
                    relative_path = _get_relative_path_from_csv(
                        file_id,
                        dup_folder_id,
                        all_rows,
                    )

                    # Ensure folder structure exists in destination folder
                    dest_parent_id = _ensure_folder_structure(
                        service,
                        first_folder_id,
                        relative_path,
                        drive_config.drive_id,
                        dry_run,
                    )

                    # Record the move operation with full information for revert
                    # Save the actual parent (which might be a subfolder) for accurate revert
                    source_parent_id = current_parents[0] if current_parents else ""
                    move_record = {
                        "action": "move",
                        "file_id": file_id,
                        "file_name": file_name,
                        "source_folder_id": dup_folder_id,  # Root duplicate folder
                        "source_parent_id": source_parent_id,  # Actual parent (may be subfolder)
                        "dest_folder_id": dest_parent_id,  # Destination folder (may be subfolder)
                        "folder_id": "",
                        "folder_name": "",
                        "dry_run": str(dry_run),
                    }
                    output_rows.append(move_record)

                    if dry_run:
                        if relative_path:
                            logger.info(
                                "    [dry-run] Would move {} ({}) from {} to {} (preserving path: {})",
                                file_name,
                                file_id,
                                ",".join(current_parents),
                                dest_parent_id,
                                "/".join(relative_path),
                            )
                        else:
                            logger.info(
                                "    [dry-run] Would move {} ({}) from {} to {}",
                                file_name,
                                file_id,
                                ",".join(current_parents),
                                dest_parent_id,
                            )
                    else:
                        try:
                            updated = move_file(
                                service,
                                file_id,
                                dest_parent_id,
                                current_parents,
                                drive_config.drive_id,
                            )
                            if relative_path:
                                logger.info(
                                    "    Moved {} ({}) from {} to {} (preserved path: {})",
                                    file_name,
                                    file_id,
                                    ",".join(current_parents),
                                    dest_parent_id,
                                    "/".join(relative_path),
                                )
                            else:
                                logger.info(
                                    "    Moved {} ({}) from {} to {}",
                                    file_name,
                                    file_id,
                                    ",".join(current_parents),
                                    dest_parent_id,
                                )
                        except Exception as e:
                            logger.error(
                                "    Failed to move {} ({}): {}",
                                file_name,
                                file_id,
                                e,
                            )

                except Exception as e:
                    logger.error(
                        "    Failed to get metadata for {} ({}): {}",
                        file_name,
                        file_id,
                        e,
                    )

            # After moving all files, check if folder is empty and delete it
            # Check Google Drive API to see if folder has any remaining children
            can_delete = True
            if not dry_run:
                try:
                    remaining_children = list(
                        list_folder_children(
                            service,
                            dup_folder_id,
                            drive_config.drive_id,
                        )
                    )
                    if remaining_children:
                        logger.warning(
                            "    Folder {} ({}) still has {} items; skipping deletion",
                            dup_folder_name,
                            dup_folder_id,
                            len(remaining_children),
                        )
                        can_delete = False
                except Exception as e:
                    logger.error(
                        "    Failed to check if folder {} ({}) is empty: {}",
                        dup_folder_name,
                        dup_folder_id,
                        e,
                    )
                    can_delete = False

            # Delete folder if it's empty (or in dry-run mode)
            if can_delete:
                # Record the delete operation
                delete_record = {
                    "action": "delete",
                    "file_id": "",
                    "file_name": "",
                    "source_folder_id": "",
                    "dest_folder_id": "",
                    "folder_id": dup_folder_id,
                    "folder_name": dup_folder_name,
                    "dry_run": str(dry_run),
                }
                output_rows.append(delete_record)

                if dry_run:
                    logger.info(
                        "    [dry-run] Would delete empty folder {} ({})",
                        dup_folder_name,
                        dup_folder_id,
                    )
                else:
                    try:
                        delete_folder(service, dup_folder_id, drive_config.drive_id)
                        logger.info(
                            "    Deleted empty folder {} ({})",
                            dup_folder_name,
                            dup_folder_id,
                        )
                    except Exception as e:
                        logger.error(
                            "    Failed to delete folder {} ({}): {}",
                            dup_folder_name,
                            dup_folder_id,
                            e,
                        )

    # Write output CSV
    if output_rows:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "action",
            "file_id",
            "file_name",
            "source_folder_id",
            "source_parent_id",
            "dest_folder_id",
            "folder_id",
            "folder_name",
            "dry_run",
        ]
        with output_csv.open("w", newline="", encoding="utf-8") as csv_handle:
            writer = csv.DictWriter(csv_handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in output_rows:
                writer.writerow(row)

        logger.info(
            "Wrote {} operations to {}",
            len(output_rows),
            output_csv,
        )
    else:
        logger.info("No operations to write")


def migrate_contact_folders(
    service,
    drive_config: DriveConfig,
    csv_file: Path = Path("data/contacts-with-old-folder.csv"),
    planfix_client: Optional[PlanfixClient] = None,
    write_to_contacts: bool = False,
) -> None:
    """
    Migrate contact folder references from old drive to new drive.
    Reads CSV, extracts folder IDs from old drive URLs, finds matching folders
    in new drive, and updates CSV with new folder URLs or error messages.
    """
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    logger.info("Reading contacts CSV from {}", csv_file)

    # Read all rows from CSV
    rows: List[Dict[str, Any]] = []
    fieldnames: Optional[List[str]] = None

    with csv_file.open(encoding="utf-8-sig", newline="") as csv_handle:
        reader = csv.DictReader(csv_handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV file {csv_file} has no headers")

        fieldnames = list(reader.fieldnames)
        required_columns = {
            "Дополнительная информация",
            "Ссылка на Google Drive папку клиента",
        }
        if not required_columns.issubset(set(fieldnames)):
            raise ValueError(
                f"CSV must contain columns {sorted(required_columns)}, got {fieldnames}"
            )

        for row in reader:
            rows.append(row)

    logger.info("Processing {} rows from CSV", len(rows))

    files_resource = service.files()
    updated_count = 0
    skipped_count = 0
    error_count = 0

    # Helper function to extract folder ID from URL or text
    def extract_folder_id_from_text(text: str) -> Optional[str]:
        """Extract folder ID from Google Drive URL or text containing URL."""
        if not text:
            return None

        # Try to find folder ID using regex pattern
        match = re.search(r"/folders/([A-Za-z0-9_-]+)", text)
        if match:
            return match.group(1)

        return None

    # Process each row
    for idx, row in enumerate(rows, start=2):
        # Skip if already has a link
        existing_link = (row.get("Ссылка на Google Drive папку клиента") or "").strip()
        if existing_link:
            skipped_count += 1
            logger.debug("Row {}: Skipping, already has link", idx)
            continue

        additional_info = (row.get("Дополнительная информация") or "").strip()
        if not additional_info:
            error_count += 1
            row["Ссылка на Google Drive папку клиента"] = (
                "error: no additional information"
            )
            logger.warning("Row {}: No additional information", idx)
            continue

        # Extract folder ID from additional info
        old_folder_id = extract_folder_id_from_text(additional_info)
        if not old_folder_id:
            error_count += 1
            row["Ссылка на Google Drive папку клиента"] = (
                "error: could not extract folder ID from additional information"
            )
            logger.warning(
                "Row {}: Could not extract folder ID from: {}",
                idx,
                additional_info[:100],
            )
            continue

        try:
            # Get folder name from old drive
            logger.debug("Row {}: Getting folder name for ID {}", idx, old_folder_id)
            folder_metadata = files_resource.get(
                fileId=old_folder_id,
                fields="name",
                supportsAllDrives=True,
            ).execute()

            folder_name = folder_metadata.get("name", "").strip()
            if not folder_name:
                error_count += 1
                row["Ссылка на Google Drive папку клиента"] = (
                    "error: folder name is empty"
                )
                logger.warning(
                    "Row {}: Folder name is empty for ID {}", idx, old_folder_id
                )
                continue

            # Normalize Unicode to NFC form to handle characters like 'й' consistently
            # This ensures matching even if one drive uses NFC and the other uses NFD
            folder_name = normalize("NFC", folder_name)

            logger.debug("Row {}: Found folder name: {}", idx, folder_name)

            # Find matching folder in new drive
            new_folder = find_child_folder(
                service,
                parent_id=drive_config.root_folder_id,
                name=folder_name,
                drive_id=drive_config.drive_id,
            )

            if new_folder:
                new_folder_id = new_folder.get("id")
                if new_folder_id:
                    folder_url = (
                        f"https://drive.google.com/drive/folders/{new_folder_id}"
                    )
                    row["Ссылка на Google Drive папку клиента"] = folder_url
                    updated_count += 1
                    logger.info(
                        "Row {}: Found matching folder '{}' -> {}",
                        idx,
                        folder_name,
                        folder_url,
                    )
                else:
                    error_count += 1
                    row["Ссылка на Google Drive папку клиента"] = (
                        "error: found folder but ID is missing"
                    )
                    logger.warning("Row {}: Found folder but ID is missing", idx)
            else:
                error_count += 1
                row["Ссылка на Google Drive папку клиента"] = (
                    f"error: folder '{folder_name}' not found in new drive"
                )
                logger.warning(
                    "Row {}: Folder '{}' not found in new drive",
                    idx,
                    folder_name,
                )

        except Exception as e:
            error_count += 1
            error_msg = f"error: {str(e)}"
            row["Ссылка на Google Drive папку клиента"] = error_msg
            logger.error("Row {}: Failed to process: {}", idx, e)

        if (idx - 1) % 10 == 0:
            logger.debug("Processed {}/{} rows", idx - 1, len(rows))

    # Write updated CSV back
    logger.info("Writing updated CSV to {}", csv_file)
    csv_file.parent.mkdir(parents=True, exist_ok=True)

    with csv_file.open("w", newline="", encoding="utf-8") as csv_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    # Update contacts in Planfix if requested
    planfix_updated_count = 0
    planfix_error_count = 0

    if write_to_contacts and planfix_client:
        logger.info("Updating contacts in Planfix...")
        for idx, row in enumerate(rows, start=2):
            folder_link = (
                row.get("Ссылка на Google Drive папку клиента") or ""
            ).strip()
            contact_number = (row.get("Номер") or "").strip()

            # Skip if folder link contains "error" or is empty
            if not folder_link or "error" in folder_link.lower():
                continue

            # Skip if contact number is missing
            if not contact_number:
                logger.warning(
                    "Row {}: Skipping Planfix update, missing contact number", idx
                )
                continue

            try:
                planfix_client.update_contact(contact_number, folder_link)
                planfix_updated_count += 1
                logger.info(
                    "Row {}: Updated contact {} in Planfix", idx, contact_number
                )
            except Exception as e:
                planfix_error_count += 1
                logger.error(
                    "Row {}: Failed to update contact {} in Planfix: {}",
                    idx,
                    contact_number,
                    e,
                )

    logger.info("Migration completed:")
    logger.info("  Total rows: {}", len(rows))
    logger.info("  Updated: {}", updated_count)
    logger.info("  Skipped (already had link): {}", skipped_count)
    logger.info("  Errors: {}", error_count)
    if write_to_contacts and planfix_client:
        logger.info("  Planfix updates: {}", planfix_updated_count)
        logger.info("  Planfix errors: {}", planfix_error_count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drive audit commands")
    parser.add_argument(
        "--config", default="data/config.yml", help="Path to configuration file"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    move_parser = subparsers.add_parser(
        "move_files_to_public_folder",
        help="Move files that match the configured pattern to the public folder",
    )
    move_parser.add_argument(
        "--dry-run", action="store_true", help="Show actions without moving files"
    )

    csv_parser = subparsers.add_parser(
        "move_files_csv",
        help="Move explicit file list from a TSV/CSV manifest into each client's public folder",
    )
    csv_parser.add_argument(
        "--csv-file", help="Path to the TSV/CSV manifest generated manually"
    )
    csv_parser.add_argument(
        "--dry-run", action="store_true", help="Show actions without moving files"
    )

    compare_parser = subparsers.add_parser(
        "compare_files",
        help="Compare two CSV exports by location and write the differences",
    )
    compare_parser.add_argument("csv_old", help="Path to the baseline CSV export")
    compare_parser.add_argument("csv_new", help="Path to the new CSV export")

    recheck_parser = subparsers.add_parser(
        "recheck_files",
        help="Recheck files from Google Drive by file_id or location from CSV",
    )
    recheck_parser.add_argument(
        "--csv-file",
        help="CSV file with file_id or location column to recheck",
    )
    recheck_parser.add_argument(
        "--file-ids",
        nargs="+",
        help="List of file IDs to recheck directly",
    )
    recheck_parser.add_argument(
        "--output",
        help="Output CSV file path (default: data/recheck_results.csv)",
    )

    migrate_parser = subparsers.add_parser(
        "migrate_contact_folders",
        help="Migrate contact folder references from old drive to new drive",
    )
    migrate_parser.add_argument(
        "--write-to-contacts",
        action="store_true",
        help="Update contacts in Planfix with Google Drive folder URLs",
    )

    merge_parser = subparsers.add_parser(
        "merge_client_folders",
        help="Merge duplicate folders at depth=1 by moving files and deleting empty duplicates",
    )
    merge_parser.add_argument(
        "--csv-file",
        default="data/new_disk/new_files.csv",
        help="Path to CSV file with full file structure (default: data/new_disk/new_files.csv)",
    )
    merge_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions without executing",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config_data = load_config(args.config)

    log_level = config_data.get("logLevel", "INFO").upper()
    if args.debug:
        log_level = "DEBUG"

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    command_log_files = {
        "move_files_to_public_folder": "move_files_to_public_folder.log",
        "move_files_csv": "move_files_csv.log",
        "migrate_contact_folders": "migrate_contact_folders.log",
        "merge_client_folders": "merge_client_folders.log",
    }
    log_file_name = command_log_files.get(args.command, f"{args.command}.log")
    log_file_path = Path("data") / log_file_name

    configure_logger(
        log_level=log_level,
        log_file_path=log_file_path,
    )

    logger.info("Loading configuration from {}", args.config)

    drive_config = DriveConfig.from_dict(config_data)
    service = get_service(drive_config)

    if args.command == "move_files_to_public_folder":
        command_config = config_data.get("commands", {}).get(
            "move_files_to_public_folder", {}
        )
        configured_patterns = command_config.get("file_match")
        configured_mime_types = command_config.get("mime_type_match")
        if configured_mime_types is None:
            configured_mime_types = command_config.get("mimeType_match")

        if not configured_patterns:
            raise ValueError(
                "commands.move_files_to_public_folder.file_match must be configured"
            )

        if isinstance(configured_patterns, str):
            file_matches = [configured_patterns]
        elif isinstance(configured_patterns, list) and all(
            isinstance(pattern, str) for pattern in configured_patterns
        ):
            file_matches = configured_patterns
        else:
            raise ValueError(
                "commands.move_files_to_public_folder.file_match must be a string or list of strings"
            )

        if configured_mime_types is None:
            mime_type_matches = None
        elif isinstance(configured_mime_types, str):
            mime_type_matches = [configured_mime_types]
        elif isinstance(configured_mime_types, list) and all(
            isinstance(mime, str) for mime in configured_mime_types
        ):
            mime_type_matches = configured_mime_types
        else:
            raise ValueError(
                "commands.move_files_to_public_folder.mime_type_match must be a string or list of strings"
            )

        moved_files = move_files_to_public_folder(
            service, drive_config, file_matches, args.dry_run, mime_type_matches
        )
        logger.info("{} files processed", len(moved_files))
    elif args.command == "move_files_csv":
        command_config = config_data.get("commands", {}).get("move_files_csv", {})
        csv_file = (
            args.csv_file or command_config.get("csv_file") or "data/move_files.csv"
        )
        moved_files = move_files_from_csv(service, drive_config, csv_file, args.dry_run)
        logger.info("{} files processed", len(moved_files))
    elif args.command == "compare_files":
        compare_config = config_data.get("compare", {})
        ignore_public_subdir = compare_config.get("ignore_public_subdir", False)
        normalize_file_names = compare_config.get("normalize_file_names", False)
        ignore_format_differences = compare_config.get(
            "ignore_format_differences", False
        )
        ignore_duplicate_suffixes = compare_config.get(
            "ignore_duplicate_suffixes", False
        )
        ignore_folders = compare_config.get("ignore_folders", [])
        public_subdir = drive_config.public_subdir

        logger.info(
            "Compare configuration: ignore_public_subdir={}, normalize_file_names={}, ignore_format_differences={}, ignore_duplicate_suffixes={}, ignore_folders={}",
            ignore_public_subdir,
            normalize_file_names,
            ignore_format_differences,
            ignore_duplicate_suffixes,
            ignore_folders,
        )

        result = compare_files_by_location(
            Path(args.csv_old),
            Path(args.csv_new),
            ignore_public_subdir=ignore_public_subdir,
            public_subdir=public_subdir,
            normalize_file_names=normalize_file_names,
            ignore_format_differences=ignore_format_differences,
            ignore_duplicate_suffixes=ignore_duplicate_suffixes,
            ignore_folders=ignore_folders if ignore_folders else None,
        )

        # Output statistics
        stats = result.get("stats", {})
        logger.info("=" * 60)
        logger.info("Comparison Statistics:")
        logger.info("  Total rows in old CSV: {}", stats.get("total_rows_old", 0))
        logger.info("  Total rows in new CSV: {}", stats.get("total_rows_new", 0))
        logger.info(
            "  Ignored public_subdir folders (old): {}",
            stats.get("ignored_public_subdirs_old", 0),
        )
        logger.info(
            "  Ignored public_subdir folders (new): {}",
            stats.get("ignored_public_subdirs_new", 0),
        )
        logger.info(
            "  Ignored folders and their children (old): {}",
            stats.get("ignored_folders_old", 0),
        )
        logger.info(
            "  Ignored folders and their children (new): {}",
            stats.get("ignored_folders_new", 0),
        )
        logger.info("  New-only rows: {}", stats.get("new_only_rows", 0))
        logger.info("  Old-only rows: {}", stats.get("old_only_rows", 0))
        logger.info("=" * 60)
    elif args.command == "recheck_files":
        recheck_files_from_drive(
            service,
            drive_config,
            csv_file=Path(args.csv_file) if args.csv_file else None,
            file_ids=args.file_ids or [],
            output_path=(
                Path(args.output) if args.output else Path("data/recheck_results.csv")
            ),
        )
    elif args.command == "migrate_contact_folders":
        planfix_client = None
        if args.write_to_contacts:
            planfix_config = build_planfix_config(config_data)
            planfix_client = PlanfixClient(planfix_config)
        migrate_contact_folders(
            service,
            drive_config,
            planfix_client=planfix_client,
            write_to_contacts=args.write_to_contacts,
        )
    elif args.command == "merge_client_folders":
        merge_client_folders(
            service,
            drive_config,
            csv_file=Path(args.csv_file),
            dry_run=args.dry_run,
        )
    else:
        raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
