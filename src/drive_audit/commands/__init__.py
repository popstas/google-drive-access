import argparse
import sys
from pathlib import Path

from loguru import logger

from ..drive_cache import DEFAULT_FOLDER_METADATA_CACHE_TIMEOUT
from ..google_client import get_service
from ..logger_config import configure_logger
from ..main import load_config
from ..model import DriveConfig
from .compare_files import compare_files_by_location, run_compare_files
from .delete_empty_folders import delete_empty_folders, run_delete_empty_folders
from .drive_links_info import drive_links_info, run_drive_links_info
from .filter_permissions import run_filter_permissions
from .merge_client_folders import merge_client_folders, run_merge_client_folders
from .migrate_contact_folders import (
    migrate_contact_folders,
    run_migrate_contact_folders,
)
from .moderate_delete import run_moderate_delete, scan
from .move_from_csv import move_files_from_csv, run_move_files_from_csv
from .move_to_public import move_files_to_public_folder, run_move_files_to_public_folder
from .recheck_files import recheck_files_from_drive, run_recheck_files
from .remove_access import remove_access, run_remove_access

COMMAND_REGISTRY = {
    "move_files_to_public_folder": run_move_files_to_public_folder,
    "move_files_csv": run_move_files_from_csv,
    "compare_files": run_compare_files,
    "recheck_files": run_recheck_files,
    "migrate_contact_folders": run_migrate_contact_folders,
    "merge_client_folders": run_merge_client_folders,
    "delete_empty_folders": run_delete_empty_folders,
    "drive_links_info": run_drive_links_info,
    "remove_access": run_remove_access,
    "filter_permissions": run_filter_permissions,
    "moderate_delete": run_moderate_delete,
}

COMMAND_LOG_FILES = {
    "move_files_to_public_folder": "move_files_to_public_folder.log",
    "move_files_csv": "move_files_csv.log",
    "migrate_contact_folders": "migrate_contact_folders.log",
    "merge_client_folders": "merge_client_folders.log",
    "delete_empty_folders": "delete_empty_folders.log",
    "drive_links_info": "drive_links_info.log",
    "remove_access": "remove_access.log",
    "moderate_delete": "moderate_delete.log",
}

NO_DRIVE_CONFIG_COMMANDS = {"filter_permissions"}
NO_SERVICE_COMMANDS = {"filter_permissions"}


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

    delete_empty_parser = subparsers.add_parser(
        "delete_empty_folders",
        help="Delete client folders at depth=1 that contain only folders recursively (no files)",
    )
    delete_empty_parser.add_argument(
        "--csv-file",
        default="data/files.csv",
        help="Path to CSV file with full file structure (default: data/files.csv)",
    )
    delete_empty_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions without executing",
    )

    drive_links_parser = subparsers.add_parser(
        "drive_links_info",
        help="Check Google Drive folder URLs from CSV and retrieve folder information",
    )
    drive_links_parser.add_argument(
        "--csv-file",
        default="data/contacts-with-google-folder.csv",
        help="Path to CSV file with folder URLs (default: data/contacts-with-google-folder.csv)",
    )
    drive_links_parser.add_argument(
        "--column",
        default="Ссылка на Google Drive папку клиента",
        help="Column name containing folder URLs (default: 'Ссылка на Google Drive папку клиента')",
    )
    drive_links_parser.add_argument(
        "--output",
        default="data/drive_links_info.csv",
        help="Output CSV file path (default: data/drive_links_info.csv)",
    )
    drive_links_parser.add_argument(
        "--cache-timeout",
        type=int,
        default=DEFAULT_FOLDER_METADATA_CACHE_TIMEOUT,
        help=f"Cache timeout in seconds (default: {DEFAULT_FOLDER_METADATA_CACHE_TIMEOUT})",
    )

    remove_access_parser = subparsers.add_parser(
        "remove_access",
        help="Remove root (non-inherited) permissions from files based on CSV data",
    )
    remove_access_parser.add_argument(
        "--csv-file",
        default="data/remove-access.csv",
        help="Path to CSV file with permissions to remove (default: data/remove-access.csv)",
    )
    remove_access_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions without deleting permissions",
    )

    filter_permissions_parser = subparsers.add_parser(
        "filter_permissions",
        help="Filter permissions.csv by permission_email and save matching rows to a new CSV",
    )
    filter_permissions_parser.add_argument(
        "--emails",
        required=True,
        help="Comma-separated list of permission emails to keep (e.g. a@x.com,b@y.com)",
    )
    filter_permissions_parser.add_argument(
        "--csv-file",
        default="data/permissions.csv",
        help="Input permissions CSV path (default: data/permissions.csv)",
    )
    filter_permissions_parser.add_argument(
        "--csv-save",
        required=True,
        help="Output CSV path for filtered rows",
    )

    moderate_delete_parser = subparsers.add_parser(
        "moderate_delete",
        help="Queue items whose names contain +delete and trash approved ones",
    )
    moderate_delete_parser.add_argument(
        "action",
        choices=["scan", "watch", "apply", "report"],
        help=(
            "scan: synchronize once; watch: scan periodically; "
            "apply: trash approved rows; report: rebuild the CSV"
        ),
    )
    moderate_delete_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="scan/watch: log candidates without writing to the Sheet",
    )
    moderate_delete_parser.add_argument(
        "--apply",
        action="store_true",
        help="apply: actually move approved files to trash (default is dry-run)",
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

    log_file_name = COMMAND_LOG_FILES.get(args.command, f"{args.command}.log")
    log_file_path = Path("data") / log_file_name

    configure_logger(
        log_level=log_level,
        log_file_path=log_file_path,
    )

    logger.info("Loading configuration from {}", args.config)

    drive_config = None
    service = None

    if args.command not in NO_DRIVE_CONFIG_COMMANDS:
        drive_config = DriveConfig.from_dict(config_data)

    if args.command not in NO_SERVICE_COMMANDS:
        if drive_config is None:
            drive_config = DriveConfig.from_dict(config_data)
        service = get_service(drive_config)

    handler = COMMAND_REGISTRY.get(args.command)
    if handler is None:
        raise ValueError(f"Unknown command: {args.command}")

    handler(args, config_data, drive_config, service)


__all__ = [
    "compare_files_by_location",
    "delete_empty_folders",
    "drive_links_info",
    "main",
    "merge_client_folders",
    "migrate_contact_folders",
    "move_files_from_csv",
    "move_files_to_public_folder",
    "parse_args",
    "recheck_files_from_drive",
    "remove_access",
    "run_filter_permissions",
    "run_moderate_delete",
    "scan",
]


if __name__ == "__main__":
    main()
