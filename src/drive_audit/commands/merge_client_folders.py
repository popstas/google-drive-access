import csv
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List
from unicodedata import normalize

from loguru import logger

from ..google_client import (
    create_folder,
    delete_folder,
    find_child_folder,
    list_folder_children,
    move_file,
)
from ..model import DriveConfig


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
                "  Processing duplicate folder {} ({}) at {}",
                dup_folder_name,
                dup_folder_id,
                dup_folder_location,
            )

            # List all files and subfolders under the duplicate folder
            try:
                dup_children = list(
                    list_folder_children(
                        service,
                        dup_folder_id,
                        drive_config.drive_id,
                    )
                )
            except Exception as e:
                logger.error(
                    "    Failed to list children of folder {} ({}): {}",
                    dup_folder_name,
                    dup_folder_id,
                    e,
                )
                continue

            logger.info(
                "    Found {} children under duplicate folder",
                len(dup_children),
            )

            # Move each file from duplicate folder to first folder
            for child in dup_children:
                file_id = child.get("id")
                file_name = child.get("name", "")
                mime_type = child.get("mimeType", "")
                current_parents = child.get("parents", [])

                if not file_id or not current_parents:
                    logger.warning(
                        "    Skipping child without id or parents: {}",
                        child,
                    )
                    continue

                try:
                    # If it's a folder, preserve folder structure when moving
                    if mime_type == "application/vnd.google-apps.folder":
                        # Get relative path inside duplicate folder from CSV
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


def run_merge_client_folders(args, config_data, drive_config, service) -> None:
    merge_client_folders(
        service,
        drive_config,
        csv_file=Path(args.csv_file),
        dry_run=args.dry_run,
    )
