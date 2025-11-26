import argparse
import csv
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from .google_client import (
    ensure_public_subdir,
    get_service,
    list_folder_children,
    move_file,
)
from .main import get_log_level, load_config
from .model import DriveConfig

logger = logging.getLogger(__name__)


def build_drive_config(config_data: Dict[str, Any]) -> DriveConfig:
    drive_section = config_data["drive"]
    google_section = config_data["google"]
    scan_section = config_data.get("scan", {})
    output_section = config_data.get("output", {})

    drive_id = drive_section["id"]
    root_folder_id = drive_section.get("root_folder_id") or drive_id
    if root_folder_id == "ROOT_FOLDER_ID":
        root_folder_id = drive_id or "root"
    elif not root_folder_id:
        root_folder_id = "root"

    return DriveConfig(
        credentials_file=google_section["credentials_file"],
        delegated_user=google_section.get("delegated_user"),
        drive_id=drive_id,
        root_folder_id=root_folder_id,
        root_folder_name=drive_section["root_folder_name"],
        include_trashed=scan_section.get("include_trashed", False),
        include_shortcuts=scan_section.get("include_shortcuts", True),
        max_depth=scan_section.get("max_depth"),
        limit=scan_section.get("limit"),
        public_subdir=scan_section.get("public_subdir"),
        output_dir=output_section.get("dir", "./data"),
        yaml_file=output_section.get("yaml_file", "drive_audit.yml"),
        files_csv=output_section.get("files_csv", "files.csv"),
        permissions_csv=output_section.get("permissions_csv", "permissions.csv"),
    )


def move_files_to_public_folder(
    service, drive_config: DriveConfig, file_matches: Any, dry_run: bool
) -> List[Dict[str, Any]]:
    if not drive_config.public_subdir:
        raise ValueError("public_subdir must be configured to move files to a public folder")

    if isinstance(file_matches, str):
        file_matches = [file_matches]
    if not isinstance(file_matches, list) or not file_matches:
        raise ValueError("file_matches must be a non-empty list of regex patterns")
    if not all(isinstance(pattern, str) for pattern in file_matches):
        raise ValueError("file_matches entries must be strings")

    patterns = [re.compile(pattern, re.IGNORECASE) for pattern in file_matches]

    folder_mime = "application/vnd.google-apps.folder"
    matched_files: List[Dict[str, Any]] = []
    public_folders: Dict[str, Dict[str, Any]] = {}
    for client_folder in list_folder_children(
        service, drive_config.root_folder_id, drive_config.drive_id
    ):
        client_name = client_folder.get("name", "")
        client_folder_id = client_folder.get("id")
        if client_folder.get("mimeType") != folder_mime or not client_folder_id:
            logger.debug(
                "Skipping non-folder item %s (%s) at root level", client_name, client_folder_id
            )
            continue

        logger.debug("Scanning client folder %s (%s)", client_name, client_folder_id)
        for file_data in list_folder_children(service, client_folder_id, drive_config.drive_id):
            name = file_data.get("name", "")
            mime_type = file_data.get("mimeType", "")
            parents = file_data.get("parents", [])

            if mime_type == folder_mime:
                logger.debug(
                    "Skipping subfolder %s (%s) under %s", name, file_data.get("id"), client_name
                )
                continue

            if not any(pattern.search(name) for pattern in patterns):
                continue

            public_folder = public_folders.get(client_folder_id)
            if not public_folder:
                public_folder = ensure_public_subdir(
                    service, client_folder_id, drive_config.public_subdir, drive_config.drive_id
                )
                public_folders[client_folder_id] = public_folder

            if public_folder["id"] in parents:
                logger.debug("File %s (%s) already in public folder", name, file_data.get("id"))
                continue

            matched_files.append(
                {
                    "file": file_data,
                    "public_folder": public_folder,
                    "client_name": client_name,
                }
            )

    moved_files: List[Dict[str, Any]] = []
    for match in matched_files:
        file_data = match["file"]
        public_folder = match["public_folder"]
        file_id = file_data.get("id")
        if not file_id:
            logger.debug("Skipping file without id: %s", file_data)
            continue

        parents = file_data.get("parents", [])
        if not parents:
            logger.warning("File %s (%s) has no parents; skipping", file_data.get("name"), file_id)
            continue

        destination_parent = public_folder["id"]
        destination_path = f"{match['client_name']}/{public_folder.get('name', drive_config.public_subdir)}"

        if dry_run:
            logger.info(
                "[dry-run] Would move %s (%s) from %s to %s (%s)",
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

        updated = move_file(service, file_id, destination_parent, parents)
        updated["destination_path"] = destination_path
        moved_files.append(updated)
        logger.info(
            "Moved %s (%s) from %s to %s (%s)",
            file_data.get("name"),
            file_id,
            ",".join(parents),
            destination_parent,
            destination_path,
        )

    return moved_files


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
        if not reader.fieldnames or not required_headers.issubset(set(reader.fieldnames)):
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
                    "Row %s is missing file_id or dest_folder; skipping entry '%s'",
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
        logger.info("No actionable rows detected in %s", csv_path)
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
            logger.warning("File %s (%s) has no parents; skipping", file_metadata.get("name"), file_id)
            continue

        file_name = file_metadata.get("name") or row["name"]

        if destination_parent in parents:
            logger.info(
                "File %s (%s) already resides in destination %s",
                file_name,
                file_id,
                destination_parent,
            )
            continue

        if dry_run:
            logger.info(
                "[dry-run] Would move %s (%s) from %s to %s",
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

        updated = move_file(service, file_id, destination_parent, parents)
        updated["destination_parent"] = destination_parent
        moved_files.append(updated)
        logger.info(
            "Moved %s (%s) from %s to %s",
            file_name,
            file_id,
            ",".join(parents),
            destination_parent,
        )

    return moved_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drive audit commands")
    parser.add_argument("--config", default="data/config.yml", help="Path to configuration file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    move_parser = subparsers.add_parser(
        "move_files_to_public_folder", help="Move files that match the configured pattern to the public folder"
    )
    move_parser.add_argument("--dry-run", action="store_true", help="Show actions without moving files")

    csv_parser = subparsers.add_parser(
        "move_files_csv",
        help="Move explicit file list from a TSV/CSV manifest into each client's public folder",
    )
    csv_parser.add_argument("--csv-file", help="Path to the TSV/CSV manifest generated manually")
    csv_parser.add_argument("--dry-run", action="store_true", help="Show actions without moving files")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logger.info("Loading configuration from %s", args.config)
    config_data = load_config(args.config)

    log_level = get_log_level(config_data.get("logLevel", "INFO"))
    if args.debug:
        log_level = logging.DEBUG

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    log_handlers = [logging.StreamHandler(sys.stdout)]

    command_log_files = {
        "move_files_to_public_folder": "move_files_to_public_folder.log",
        "move_files_csv": "move_files_csv.log",
    }
    log_file_name = command_log_files.get(args.command, f"{args.command}.log")
    log_file_path = Path("data") / log_file_name
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    log_handlers.append(logging.FileHandler(log_file_path, encoding="utf-8"))

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=log_handlers,
        force=True,
    )
    logger.setLevel(log_level)

    drive_config = build_drive_config(config_data)
    service = get_service(drive_config)

    if args.command == "move_files_to_public_folder":
        command_config = config_data.get("commands", {}).get("move_files_to_public_folder", {})
        configured_patterns = command_config.get("file_match")

        if not configured_patterns:
            raise ValueError("commands.move_files_to_public_folder.file_match must be configured")

        if isinstance(configured_patterns, str):
            file_matches = [configured_patterns]
        elif isinstance(configured_patterns, list) and all(
            isinstance(pattern, str) for pattern in configured_patterns
        ):
            file_matches = configured_patterns
        else:
            raise ValueError("commands.move_files_to_public_folder.file_match must be a string or list of strings")

        moved_files = move_files_to_public_folder(service, drive_config, file_matches, args.dry_run)
        logger.info("%s files processed", len(moved_files))
    elif args.command == "move_files_csv":
        command_config = config_data.get("commands", {}).get("move_files_csv", {})
        csv_file = args.csv_file or command_config.get("csv_file") or "data/move_files.csv"
        moved_files = move_files_from_csv(service, drive_config, csv_file, args.dry_run)
        logger.info("%s files processed", len(moved_files))
    else:
        raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
