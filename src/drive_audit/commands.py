import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from unicodedata import normalize

from loguru import logger

from .compare import compare_files_by_location
from .google_client import get_service, move_file, get_file_permissions
from .logger_config import configure_logger
from .main import load_config
from .model import DriveConfig
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
                    owner.get("emailAddress", "") for owner in file_metadata.get("owners", [])
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
        ignore_format_differences = compare_config.get("ignore_format_differences", False)
        ignore_duplicate_suffixes = compare_config.get("ignore_duplicate_suffixes", False)
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
        logger.info("  Ignored public_subdir folders (old): {}", stats.get("ignored_public_subdirs_old", 0))
        logger.info("  Ignored public_subdir folders (new): {}", stats.get("ignored_public_subdirs_new", 0))
        logger.info("  Ignored folders and their children (old): {}", stats.get("ignored_folders_old", 0))
        logger.info("  Ignored folders and their children (new): {}", stats.get("ignored_folders_new", 0))
        logger.info("  New-only rows: {}", stats.get("new_only_rows", 0))
        logger.info("  Old-only rows: {}", stats.get("old_only_rows", 0))
        logger.info("=" * 60)
    elif args.command == "recheck_files":
        recheck_files_from_drive(
            service,
            drive_config,
            csv_file=Path(args.csv_file) if args.csv_file else None,
            file_ids=args.file_ids or [],
            output_path=Path(args.output) if args.output else Path("data/recheck_results.csv"),
        )
    else:
        raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
