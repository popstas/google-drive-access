#!/usr/bin/env python3
"""
Script to revert file moves from merge_client_folders operation.

Reads merge_client_folders.csv and moves files back from dest_folder_id to source_folder_id.
"""

import argparse
import csv
import sys
from pathlib import Path

from loguru import logger

from src.drive_audit.google_client import get_service, move_file
from src.drive_audit.logger_config import configure_logger
from src.drive_audit.main import load_config
from src.drive_audit.model import DriveConfig


def revert_merge_client_folders(
    csv_file: Path = Path("data/merge_client_folders.csv"),
    dry_run: bool = False,
    config_file: Path = Path("data/config.yml"),
) -> None:
    """
    Revert file moves from merge_client_folders operation.

    Args:
        csv_file: Path to merge_client_folders.csv file
        dry_run: If True, only log actions without executing
        config_file: Path to configuration file
    """
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    logger.info("Reading merge operations from {}", csv_file)

    # Read all move operations from CSV
    move_operations = []
    with csv_file.open(encoding="utf-8-sig", newline="") as csv_handle:
        reader = csv.DictReader(csv_handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV file {csv_file} has no headers")

        for row in reader:
            action = row.get("action", "").strip()
            if action == "move":
                file_id = row.get("file_id", "").strip()
                file_name = row.get("file_name", "").strip()
                source_folder_id = row.get("source_folder_id", "").strip()
                source_parent_id = row.get(
                    "source_parent_id", ""
                ).strip()  # Actual parent (may be subfolder)
                dest_folder_id = row.get("dest_folder_id", "").strip()

                # Use source_parent_id if available (for accurate revert), otherwise fall back to source_folder_id
                revert_to_id = (
                    source_parent_id if source_parent_id else source_folder_id
                )

                if file_id and revert_to_id and dest_folder_id:
                    move_operations.append(
                        {
                            "file_id": file_id,
                            "file_name": file_name,
                            "source_folder_id": source_folder_id,
                            "source_parent_id": source_parent_id,
                            "revert_to_id": revert_to_id,  # Where to move back
                            "dest_folder_id": dest_folder_id,
                        }
                    )

    if not move_operations:
        logger.info("No move operations found in CSV")
        return

    logger.info("Found {} move operations to revert", len(move_operations))

    # Load configuration and get service
    config_data = load_config(str(config_file))
    drive_config = DriveConfig.from_dict(config_data)
    service = get_service(drive_config)

    files_resource = service.files()
    reverted_count = 0
    error_count = 0

    # Process moves in reverse order (to handle nested structures if needed)
    for operation in reversed(move_operations):
        file_id = operation["file_id"]
        file_name = operation["file_name"]
        source_folder_id = operation["source_folder_id"]
        source_parent_id = operation.get("source_parent_id", "")
        revert_to_id = operation[
            "revert_to_id"
        ]  # Where to move back (may be subfolder)
        dest_folder_id = operation["dest_folder_id"]

        try:
            # Get current file metadata
            file_metadata = files_resource.get(
                fileId=file_id,
                fields="id,name,parents",
                supportsAllDrives=True,
            ).execute()

            current_parents = file_metadata.get("parents", [])
            if not current_parents:
                logger.warning(
                    "File {} ({}) has no parents; skipping",
                    file_name,
                    file_id,
                )
                error_count += 1
                continue

            # Check if file is in the destination folder (where we moved it)
            if dest_folder_id not in current_parents:
                logger.warning(
                    "File {} ({}) is not in expected destination folder {}; current parents: {}",
                    file_name,
                    file_id,
                    dest_folder_id,
                    ",".join(current_parents),
                )
                # Still try to move it back to source folder
                # (maybe it was already moved or is in a different location)

            # Check if file is already in the revert destination (source_parent_id or source_folder_id)
            if revert_to_id in current_parents:
                logger.info(
                    "File {} ({}) already in revert destination {}; skipping",
                    file_name,
                    file_id,
                    revert_to_id,
                )
                continue

            if dry_run:
                logger.info(
                    "[dry-run] Would move {} ({}) from {} back to {} (original parent: {})",
                    file_name,
                    file_id,
                    ",".join(current_parents),
                    revert_to_id,
                    source_parent_id if source_parent_id else source_folder_id,
                )
                reverted_count += 1
            else:
                try:
                    updated = move_file(
                        service,
                        file_id,
                        revert_to_id,
                        current_parents,
                        drive_config.drive_id,
                    )
                    logger.info(
                        "Moved {} ({}) from {} back to {} (original parent: {})",
                        file_name,
                        file_id,
                        ",".join(current_parents),
                        revert_to_id,
                        source_parent_id if source_parent_id else source_folder_id,
                    )
                    reverted_count += 1
                except Exception as e:
                    logger.error(
                        "Failed to move {} ({}) back to {}: {}",
                        file_name,
                        file_id,
                        revert_to_id,
                        e,
                    )
                    error_count += 1

        except Exception as e:
            logger.error(
                "Failed to get metadata for {} ({}): {}",
                file_name,
                file_id,
                e,
            )
            error_count += 1

    logger.info("=" * 60)
    logger.info("Revert operation completed:")
    logger.info("  Total operations: {}", len(move_operations))
    logger.info("  Reverted: {}", reverted_count)
    logger.info("  Errors: {}", error_count)
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Revert file moves from merge_client_folders operation"
    )
    parser.add_argument(
        "--csv-file",
        default="data/merge_client_folders.csv",
        help="Path to merge_client_folders.csv file (default: data/merge_client_folders.csv)",
    )
    parser.add_argument(
        "--config",
        default="data/config.yml",
        help="Path to configuration file (default: data/config.yml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions without executing",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    log_level = "DEBUG" if args.debug else "INFO"
    log_file_path = Path("data") / "revert_merge_client_folders.log"

    configure_logger(
        log_level=log_level,
        log_file_path=log_file_path,
    )

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        revert_merge_client_folders(
            csv_file=Path(args.csv_file),
            dry_run=args.dry_run,
            config_file=Path(args.config),
        )
    except Exception as e:
        logger.error("Failed to revert merge operations: {}", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
