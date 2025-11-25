import argparse
import logging
import re
import sys
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

    root_folder_id = drive_section.get("root_folder_id", drive_section["id"])
    if root_folder_id == "ROOT_FOLDER_ID":
        root_folder_id = drive_section["id"]

    return DriveConfig(
        credentials_file=google_section["credentials_file"],
        delegated_user=google_section.get("delegated_user"),
        drive_id=drive_section["id"],
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


def move_files_to_public_folder(service, drive_config: DriveConfig, file_match: str, dry_run: bool) -> List[Dict[str, Any]]:
    if not drive_config.public_subdir:
        raise ValueError("public_subdir must be configured to move files to a public folder")

    pattern = re.compile(file_match)
    public_folder = ensure_public_subdir(
        service, drive_config.root_folder_id, drive_config.public_subdir, drive_config.drive_id
    )

    matched_files: List[Dict[str, Any]] = []
    for file_data in list_folder_children(service, drive_config.root_folder_id, drive_config.drive_id):
        name = file_data.get("name", "")
        mime_type = file_data.get("mimeType", "")
        parents = file_data.get("parents", [])

        if mime_type == "application/vnd.google-apps.folder":
            logger.debug("Skipping folder %s (%s)", name, file_data.get("id"))
            continue

        if not pattern.search(name):
            continue

        if public_folder["id"] in parents:
            logger.debug("File %s (%s) already in public folder", name, file_data.get("id"))
            continue

        matched_files.append(file_data)

    moved_files: List[Dict[str, Any]] = []
    for file_data in matched_files:
        file_id = file_data.get("id")
        if not file_id:
            logger.debug("Skipping file without id: %s", file_data)
            continue

        parents = file_data.get("parents", [])
        if not parents:
            logger.warning("File %s (%s) has no parents; skipping", file_data.get("name"), file_id)
            continue

        if dry_run:
            logger.info(
                "[dry-run] Would move %s (%s) from %s to %s",
                file_data.get("name"),
                file_id,
                ",".join(parents),
                public_folder["id"],
            )
            moved_files.append({"file_id": file_id, "new_parent": public_folder["id"], "dry_run": True})
            continue

        updated = move_file(service, file_id, public_folder["id"], parents)
        moved_files.append(updated)
        logger.info(
            "Moved %s (%s) from %s to %s",
            file_data.get("name"),
            file_id,
            ",".join(parents),
            public_folder["id"],
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

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logger.info("Loading configuration from %s", args.config)
    config_data = load_config(args.config)

    log_level = get_log_level(config_data.get("logLevel", "INFO"))
    if args.debug:
        log_level = logging.DEBUG

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    logger.setLevel(log_level)

    drive_config = build_drive_config(config_data)
    service = get_service(drive_config)

    if args.command == "move_files_to_public_folder":
        command_config = config_data.get("commands", {}).get("move_files_to_public_folder", {})
        file_match = command_config.get("file_match")

        if not file_match:
            raise ValueError("commands.move_files_to_public_folder.file_match must be configured")

        moved_files = move_files_to_public_folder(service, drive_config, file_match, args.dry_run)
        logger.info("%s files processed", len(moved_files))
    else:
        raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
