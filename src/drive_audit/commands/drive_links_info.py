import csv
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from ..access_service import extract_folder_id
from ..drive_cache import DEFAULT_FOLDER_METADATA_CACHE_TIMEOUT, folder_metadata_cache
from ..google_client import get_file_permissions
from ..http_utils import LocalizedError


def drive_links_info(
    service,
    csv_file: Path = Path("data/contacts-with-google-folder.csv"),
    column: str = "Ссылка на Google Drive папку клиента",
    output_path: Path = Path("data/drive_links_info.csv"),
    cache_timeout_seconds: int = DEFAULT_FOLDER_METADATA_CACHE_TIMEOUT,
) -> None:
    """
    Read CSV with Google Drive folder URLs, retrieve folder info from API, and save results.

    Args:
        service: Google Drive service instance
        csv_file: Path to CSV file with folder URLs
        column: Column name containing the folder URLs
        output_path: Path to save the output CSV
        cache_timeout_seconds: Cache timeout in seconds (default: 3600)
    """
    if not csv_file.exists():
        logger.error("CSV file not found: {}", csv_file)
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    logger.info("Reading CSV file: {}", csv_file)

    rows = []
    with csv_file.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames or column not in reader.fieldnames:
            logger.error(
                "Column '{}' not found in CSV. Available columns: {}",
                column,
                reader.fieldnames,
            )
            raise ValueError(f"Column '{column}' not found in CSV")

        for row in reader:
            rows.append(row)

    logger.info("Found {} rows in CSV", len(rows))

    # Get original fieldnames to preserve them
    original_fieldnames = []
    with csv_file.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        original_fieldnames = list(reader.fieldnames or [])

    results = []
    success_count = 0
    error_count = 0
    empty_count = 0

    fields = "id,name,mimeType,parents,createdTime,modifiedTime,viewedByMeTime,owners,lastModifyingUser,size,webViewLink"

    for idx, row in enumerate(rows, start=2):
        folder_url = (row.get(column) or "").strip()

        # Start with all original CSV columns
        result_row = {"source_row": idx}
        result_row.update(row)

        if not folder_url:
            empty_count += 1
            logger.debug("Row {}: Empty URL, skipping", idx)
            # Add empty Drive metadata fields
            result_row.update(
                {
                    "folder_id": "",
                    "folder_name": "",
                    "mime_type": "",
                    "parents": "",
                    "created": "",
                    "modified": "",
                    "viewed": "",
                    "size_bytes": "",
                    "owner_emails": "",
                    "last_modifying_user_email": "",
                    "permissions_count": "",
                    "web_view_link": "",
                }
            )
            results.append(result_row)
            continue

        try:
            folder_id = extract_folder_id(folder_url)
            logger.debug("Row {}: Extracted folder ID: {}", idx, folder_id)

            # Try to get folder metadata from cache
            folder_metadata = folder_metadata_cache.get_cached_metadata(
                folder_id, cache_timeout_seconds
            )

            if folder_metadata is None:
                # Get folder metadata from API
                folder_metadata = (
                    service.files()
                    .get(
                        fileId=folder_id,
                        fields=fields,
                        supportsAllDrives=True,
                    )
                    .execute()
                )
                # Store in cache
                folder_metadata_cache.store_cached_metadata(
                    folder_id, folder_metadata, cache_timeout_seconds
                )
                logger.debug("Row {}: Fetched and cached folder metadata", idx)
            else:
                logger.debug("Row {}: Using cached folder metadata", idx)

            # Get permissions
            try:
                permissions = get_file_permissions(service, folder_id)
                permissions_count = len(permissions)
            except Exception as e:
                logger.warning(
                    "Row {}: Failed to get permissions for {}: {}", idx, folder_id, e
                )
                permissions_count = 0

            # Add Drive metadata to the result row
            result_row.update(
                {
                    "folder_id": folder_metadata.get("id", ""),
                    "folder_name": folder_metadata.get("name", ""),
                    "mime_type": folder_metadata.get("mimeType", ""),
                    "parents": ",".join(folder_metadata.get("parents", [])),
                    "created": folder_metadata.get("createdTime", ""),
                    "modified": folder_metadata.get("modifiedTime", ""),
                    "viewed": folder_metadata.get("viewedByMeTime", ""),
                    "size_bytes": folder_metadata.get("size", ""),
                    "owner_emails": ",".join(
                        owner.get("emailAddress", "")
                        for owner in folder_metadata.get("owners", [])
                    ),
                    "last_modifying_user_email": (
                        folder_metadata.get("lastModifyingUser", {}).get(
                            "emailAddress", ""
                        )
                    ),
                    "permissions_count": str(permissions_count),
                    "web_view_link": folder_metadata.get("webViewLink", ""),
                }
            )

            results.append(result_row)
            success_count += 1
            logger.info(
                "Row {}: Retrieved info for folder '{}'", idx, result_row["folder_name"]
            )

        except LocalizedError as e:
            error_count += 1
            logger.error(
                "Row {}: Failed to extract folder ID from URL '{}': {}",
                idx,
                folder_url,
                e,
            )
            result_row.update(
                {
                    "folder_id": "",
                    "folder_name": "",
                    "mime_type": "",
                    "parents": "",
                    "created": "",
                    "modified": "",
                    "viewed": "",
                    "size_bytes": "",
                    "owner_emails": "",
                    "last_modifying_user_email": "",
                    "permissions_count": "",
                    "web_view_link": "",
                    "error": str(e),
                }
            )
            results.append(result_row)
        except Exception as e:
            error_count += 1
            logger.error(
                "Row {}: Failed to retrieve folder info from URL '{}': {}",
                idx,
                folder_url,
                e,
            )
            result_row.update(
                {
                    "folder_id": "",
                    "folder_name": "",
                    "mime_type": "",
                    "parents": "",
                    "created": "",
                    "modified": "",
                    "viewed": "",
                    "size_bytes": "",
                    "owner_emails": "",
                    "last_modifying_user_email": "",
                    "permissions_count": "",
                    "web_view_link": "",
                    "error": str(e),
                }
            )
            results.append(result_row)

    # Write results to CSV
    if results:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build fieldnames: source_row, original fields, new Drive metadata fields
        drive_metadata_fields = [
            "folder_id",
            "folder_name",
            "mime_type",
            "parents",
            "created",
            "modified",
            "viewed",
            "size_bytes",
            "owner_emails",
            "last_modifying_user_email",
            "permissions_count",
            "web_view_link",
        ]

        fieldnames = ["source_row"] + original_fieldnames + drive_metadata_fields

        # Add error field if any errors occurred
        if error_count > 0:
            fieldnames.append("error")

        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in results:
                writer.writerow(row)

        logger.info("Wrote {} results to {}", len(results), output_path)
    else:
        logger.warning("No results to write")

    logger.info("Drive links info completed:")
    logger.info("  Total rows: {}", len(rows))
    logger.info("  Empty URLs: {}", empty_count)
    logger.info("  Success: {}", success_count)
    logger.info("  Errors: {}", error_count)


def run_drive_links_info(args, config_data, drive_config, service) -> None:
    drive_links_info(
        service,
        csv_file=Path(args.csv_file),
        column=args.column,
        output_path=Path(args.output),
        cache_timeout_seconds=args.cache_timeout,
    )
