import argparse
import os
import sys
from pathlib import Path

import yaml
from loguru import logger

from .export_csv import save_files_csv, save_permissions_csv
from .export_yaml import save_yaml
from .google_client import get_file_permissions, get_service, list_files
from .logger_config import configure_logger
from .model import DriveConfig
from .scanner import build_file_tree


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Google Drive Audit CLI")
    parser.add_argument(
        "--config", default="data/config.yml", help="Path to configuration file"
    )
    parser.add_argument("--drive-id", help="Shared Drive ID")
    parser.add_argument("--root-folder-id", help="Root folder ID")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # Load config first to get logLevel
    try:
        config_data = load_config(args.config)
    except FileNotFoundError:
        # Use basic logger before configuration
        from loguru import logger as temp_logger
        temp_logger.error(f"Config file not found: {args.config}")
        sys.exit(1)

    # Configure logging from config
    log_level = config_data.get("logLevel", "INFO").upper()
    if args.debug:
        log_level = "DEBUG"

    log_file_path = Path("data") / "app.log"
    configure_logger(
        log_level=log_level,
        log_file_path=log_file_path,
    )

    logger.info(f"Loading configuration from {args.config}")

    drive_section = config_data.setdefault("drive", {})

    # Override config with CLI args, allow empty drive.id
    if args.drive_id:
        drive_section["id"] = args.drive_id
    drive_section["id"] = drive_section.get("id", "") or ""

    if args.root_folder_id:
        drive_section["root_folder_id"] = args.root_folder_id

    config = DriveConfig.from_dict(config_data)

    logger.info("Initializing Google Drive Service...")
    try:
        service = get_service(config)
    except Exception as e:
        logger.error(f"Failed to initialize service: {e}")
        sys.exit(1)

    logger.info(f"Scanning Drive ID: {config.drive_id}")

    try:
        # 1. List all files
        logger.info("Listing files...")
        raw_files = list(list_files(service, config.drive_id, limit=config.limit))
        if config.limit:
            logger.info(
                f"Found {len(raw_files)} files/folders (limited to {config.limit})."
            )
        else:
            logger.info(f"Found {len(raw_files)} files/folders.")

        # 2. Fetch permissions for each file
        logger.info("Fetching permissions for files...")
        files_with_perms = 0
        total_perms = 0
        for idx, file_data in enumerate(raw_files, 1):
            file_id = file_data.get("id")
            if file_id:
                permissions = get_file_permissions(service, file_id)
                file_data["permissions"] = permissions
                if permissions:
                    files_with_perms += 1
                    total_perms += len(permissions)
                if idx % 10 == 0:
                    logger.debug(
                        f"Fetched permissions for {idx}/{len(raw_files)} files..."
                    )
        logger.info(
            f"Finished fetching permissions. {files_with_perms} files have permissions ({total_perms} total permissions)."
        )

        # 3. Build Tree & Process
        logger.info("Processing files and building tree...")
        processed_files = build_file_tree(raw_files, config)
        logger.info(f"Processed {len(processed_files)} files after filtering.")

        # Debug: Check owners and permissions
        files_with_owners = sum(1 for f in processed_files if f.owners)
        files_with_permissions = sum(
            1 for f in processed_files if f.access and f.access.permissions
        )
        total_permissions = sum(
            len(f.access.permissions) if f.access else 0 for f in processed_files
        )
        logger.debug(
            f"Debug: {files_with_owners} files have owners, {files_with_permissions} files have permissions ({total_permissions} total)."
        )

        # 4. Export
        if not os.path.exists(config.output_dir):
            os.makedirs(config.output_dir)

        yaml_path = os.path.join(config.output_dir, config.yaml_file)
        files_csv_path = os.path.join(config.output_dir, config.files_csv)
        perms_csv_path = os.path.join(config.output_dir, config.permissions_csv)

        logger.info(f"Exporting to YAML: {yaml_path}")
        save_yaml(processed_files, config, yaml_path)

        logger.info(f"Exporting Files CSV: {files_csv_path}")
        save_files_csv(processed_files, files_csv_path)

        logger.info(f"Exporting Permissions CSV: {perms_csv_path}")
        save_permissions_csv(processed_files, perms_csv_path)

        logger.info("Audit complete.")

    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
