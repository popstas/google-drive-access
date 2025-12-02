import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from ..model import DriveConfig


def _folder_contains_files_recursively(
    client_id: str,
    all_rows: List[Dict[str, Any]],
) -> bool:
    """
    Check if a client folder contains any files recursively (not just folders) using CSV lookup.
    Returns True if any file (non-folder) is found, False if only folders exist.

    Args:
        client_id: The file_id of the client folder (depth=1 folder)
        all_rows: All rows from the CSV file
    """
    # Check all rows in CSV where client_id matches
    for row in all_rows:
        row_client_id = row.get("client_id", "").strip()
        row_type = row.get("type", "").strip().lower()

        # Skip if client_id doesn't match
        if row_client_id != client_id:
            continue

        # If it's a file (not a folder), we found a file
        if row_type == "file":
            return True

    # No files found for this client folder
    return False


def delete_empty_folders(
    service,
    drive_config: DriveConfig,
    csv_file: Path = Path("data/files.csv"),
    dry_run: bool = False,
) -> None:
    """
    Delete client folders (depth=1) that contain only folders recursively (no files).

    Args:
        service: Google Drive service object
        drive_config: Drive configuration
        csv_file: Path to CSV file with full file structure (default: data/files.csv)
        dry_run: If True, only log actions without executing
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

    # Filter client folders at depth=1
    depth_1_folders = [
        row
        for row in all_rows
        if row.get("type") == "folder" and row.get("depth") == "1"
    ]

    logger.info("Found {} client folders at depth=1", len(depth_1_folders))

    if not depth_1_folders:
        logger.info("No client folders found")
        return

    empty_folders: List[Dict[str, Any]] = []
    folders_with_files: List[Dict[str, Any]] = []
    error_folders: List[Dict[str, Any]] = []

    # Check each client folder
    for folder in depth_1_folders:
        folder_id = folder.get("file_id", "").strip()
        folder_name = folder.get("name", "").strip()
        folder_location = folder.get("location", "").strip()

        if not folder_id:
            logger.warning(
                "Skipping folder without file_id: {}",
                folder_name or folder_location,
            )
            continue

        logger.info(
            "Checking folder {} ({})",
            folder_name,
            folder_id,
        )

        try:
            contains_files = _folder_contains_files_recursively(folder_id, all_rows)
            if contains_files:
                folders_with_files.append(folder)
            else:
                empty_folders.append(folder)
        except Exception as e:
            logger.error(
                "Error checking folder {} ({}): {}",
                folder_name,
                folder_id,
                e,
            )
            error_folders.append(folder)

    logger.info("Summary:")
    logger.info("  Folders with files: {}", len(folders_with_files))
    logger.info("  Empty folders: {}", len(empty_folders))
    logger.info("  Errors: {}", len(error_folders))

    if not empty_folders:
        logger.info("No empty folders found")
        return

    logger.info("Processing empty folders...")
    for folder in empty_folders:
        folder_id = folder.get("file_id", "").strip()
        folder_name = folder.get("name", "").strip()
        folder_location = folder.get("location", "").strip()

        logger.info(
            "Deleting empty folder {} ({}) at {}",
            folder_name,
            folder_id,
            folder_location,
        )

        if dry_run:
            logger.info("[dry-run] Would delete folder {} ({})", folder_name, folder_id)
            continue

        try:
            service.files().delete(
                fileId=folder_id,
                supportsAllDrives=True,
                supportsTeamDrives=True,
            ).execute()
            logger.info("Deleted folder {} ({})", folder_name, folder_id)
        except Exception as e:
            logger.error(
                "Failed to delete folder {} ({}): {}", folder_name, folder_id, e
            )


def run_delete_empty_folders(args, config_data, drive_config, service) -> None:
    delete_empty_folders(
        service,
        drive_config,
        csv_file=Path(args.csv_file),
        dry_run=args.dry_run,
    )
