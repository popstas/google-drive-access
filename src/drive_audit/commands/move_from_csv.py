import csv
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from ..google_client import move_file
from ..model import DriveConfig


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


def run_move_files_from_csv(args, config_data, drive_config, service) -> None:
    command_config = config_data.get("commands", {}).get("move_files_csv", {})
    csv_file = args.csv_file or command_config.get("csv_file") or "data/move_files.csv"
    moved_files = move_files_from_csv(service, drive_config, csv_file, args.dry_run)
    logger.info("{} files processed", len(moved_files))
