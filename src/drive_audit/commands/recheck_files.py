import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from ..google_client import get_file_permissions
from ..model import DriveConfig


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
                    owner.get("emailAddress", "")
                    for owner in file_metadata.get("owners", [])
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


def run_recheck_files(args, config_data, drive_config, service) -> None:
    recheck_files_from_drive(
        service,
        drive_config,
        csv_file=Path(args.csv_file) if args.csv_file else None,
        file_ids=args.file_ids or [],
        output_path=(
            Path(args.output) if args.output else Path("data/recheck_results.csv")
        ),
    )
