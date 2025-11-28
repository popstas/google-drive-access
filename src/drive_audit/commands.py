import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger

from .google_client import get_service, move_file
from .logger_config import configure_logger
from .main import load_config
from .model import DriveConfig
from .public_folder_ops import (
    collect_public_folder_matches,
    execute_public_folder_moves,
    validate_public_folder_move_inputs,
)

DEFAULT_COMPARE_NEW_PATH = Path("data") / "compare_only_new.csv"
DEFAULT_COMPARE_OLD_PATH = Path("data") / "compare_only_old.csv"


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


def read_csv_rows(csv_path: Path) -> tuple[List[Dict[str, str]], Sequence[str]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    if not csv_path.is_file():
        raise ValueError(f"CSV path must be a file: {csv_path}")

    with csv_path.open(encoding="utf-8-sig", newline="") as csv_handle:
        reader = csv.DictReader(csv_handle)
        if not reader.fieldnames or "location" not in reader.fieldnames:
            raise ValueError(
                "CSV must include a 'location' column to support comparison"
            )
        rows = [row for row in reader]

    return rows, reader.fieldnames


def build_fieldnames(primary: Sequence[str], secondary: Sequence[str]) -> List[str]:
    if list(primary) == list(secondary):
        return list(primary)

    merged: List[str] = []
    for field in primary:
        if field not in merged:
            merged.append(field)
    for field in secondary:
        if field not in merged:
            merged.append(field)
    return merged


MIME_NORMALIZATION_GROUPS = {
    "spreadsheet": {
        "mimes": {
            "application/vnd.google-apps.spreadsheet",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
        "extensions": {".xlsx"},
    },
    "document": {
        "mimes": {
            "application/vnd.google-apps.document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
        "extensions": {".docx"},
    },
}


def normalize_location(row: Dict[str, str]) -> str:
    location = (row.get("location") or "").strip()
    mime_type = (row.get("mimeType") or "").strip()
    suffix = Path(location).suffix.lower()

    matched_group = None
    for group_name, group_values in MIME_NORMALIZATION_GROUPS.items():
        if mime_type in group_values["mimes"]:
            matched_group = group_name
            break
        if suffix in group_values["extensions"]:
            matched_group = group_name
            break

    if matched_group:
        extensions = MIME_NORMALIZATION_GROUPS[matched_group]["extensions"]
        if suffix in extensions:
            location = location[: -len(suffix)]

    return location


def compare_files_by_location(
    csv_old: Path,
    csv_new: Path,
    output_new_path: Path = DEFAULT_COMPARE_NEW_PATH,
    output_old_path: Path = DEFAULT_COMPARE_OLD_PATH,
) -> Dict[str, Path]:
    old_rows, old_fields = read_csv_rows(csv_old)
    new_rows, new_fields = read_csv_rows(csv_new)

    combined_fieldnames = build_fieldnames(old_fields, new_fields)

    old_locations = {normalize_location(row) for row in old_rows}
    new_locations = {normalize_location(row) for row in new_rows}

    new_only_rows = [
        row
        for row in new_rows
        if normalize_location(row) not in old_locations
    ]
    old_only_rows = [
        row
        for row in old_rows
        if normalize_location(row) not in new_locations
    ]

    def write_rows(rows: List[Dict[str, str]], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as csv_handle:
            writer = csv.DictWriter(csv_handle, fieldnames=combined_fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {field: row.get(field, "") for field in combined_fieldnames}
                )
        return output_path

    output_new = write_rows(new_only_rows, output_new_path)
    output_old = write_rows(old_only_rows, output_old_path)

    logger.info(
        "Wrote {} new-only rows to {} and {} old-only rows to {}",
        len(new_only_rows),
        output_new,
        len(old_only_rows),
        output_old,
    )

    return {"new": output_new, "old": output_old}


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
        compare_files_by_location(Path(args.csv_old), Path(args.csv_new))
    else:
        raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
