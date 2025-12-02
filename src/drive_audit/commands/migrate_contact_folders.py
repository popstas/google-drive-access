import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from unicodedata import normalize

from loguru import logger

from ..google_client import find_child_folder
from ..model import DriveConfig
from ..planfix_client import PlanfixClient


def migrate_contact_folders(
    service,
    drive_config: DriveConfig,
    csv_file: Path = Path("data/contacts-with-old-folder.csv"),
    planfix_client: Optional[PlanfixClient] = None,
    write_to_contacts: bool = False,
) -> None:
    """
    Migrate contact folder references from old drive to new drive.
    Reads CSV, extracts folder IDs from old drive URLs, finds matching folders
    in new drive, and updates CSV with new folder URLs or error messages.
    """
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    logger.info("Reading contacts CSV from {}", csv_file)

    # Read all rows from CSV
    rows: List[Dict[str, Any]] = []
    fieldnames: Optional[List[str]] = None

    with csv_file.open(encoding="utf-8-sig", newline="") as csv_handle:
        reader = csv.DictReader(csv_handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV file {csv_file} has no headers")

        fieldnames = list(reader.fieldnames)
        required_columns = {
            "Дополнительная информация",
            "Ссылка на Google Drive папку клиента",
        }
        if not required_columns.issubset(set(fieldnames)):
            raise ValueError(
                f"CSV must contain columns {sorted(required_columns)}, got {fieldnames}"
            )

        for row in reader:
            rows.append(row)

    logger.info("Processing {} rows from CSV", len(rows))

    files_resource = service.files()
    updated_count = 0
    skipped_count = 0
    error_count = 0

    # Helper function to extract folder ID from URL or text
    def extract_folder_id_from_text(text: str) -> Optional[str]:
        """Extract folder ID from Google Drive URL or text containing URL."""
        if not text:
            return None

        # Try to find folder ID using regex pattern
        match = re.search(r"/folders/([A-Za-z0-9_-]+)", text)
        if match:
            return match.group(1)

        return None

    # Process each row
    for idx, row in enumerate(rows, start=2):
        # Skip if already has a link
        existing_link = (row.get("Ссылка на Google Drive папку клиента") or "").strip()
        if existing_link:
            skipped_count += 1
            logger.debug("Row {}: Skipping, already has link", idx)
            continue

        additional_info = (row.get("Дополнительная информация") or "").strip()
        if not additional_info:
            error_count += 1
            row["Ссылка на Google Drive папку клиента"] = (
                "error: no additional information"
            )
            logger.warning("Row {}: No additional information", idx)
            continue

        # Extract folder ID from additional info
        old_folder_id = extract_folder_id_from_text(additional_info)
        if not old_folder_id:
            error_count += 1
            row["Ссылка на Google Drive папку клиента"] = (
                "error: could not extract folder ID from additional information"
            )
            logger.warning(
                "Row {}: Could not extract folder ID from: {}",
                idx,
                additional_info[:100],
            )
            continue

        try:
            # Get folder name from old drive
            logger.debug("Row {}: Getting folder name for ID {}", idx, old_folder_id)
            folder_metadata = files_resource.get(
                fileId=old_folder_id,
                fields="name",
                supportsAllDrives=True,
            ).execute()

            folder_name = folder_metadata.get("name", "").strip()
            if not folder_name:
                error_count += 1
                row["Ссылка на Google Drive папку клиента"] = (
                    "error: folder name is empty"
                )
                logger.warning(
                    "Row {}: Folder name is empty for ID {}", idx, old_folder_id
                )
                continue

            # Normalize Unicode to NFC form to handle characters like 'й' consistently
            # This ensures matching even if one drive uses NFC and the other uses NFD
            folder_name = normalize("NFC", folder_name)

            logger.debug("Row {}: Found folder name: {}", idx, folder_name)

            # Find matching folder in new drive
            new_folder = find_child_folder(
                service,
                parent_id=drive_config.root_folder_id,
                name=folder_name,
                drive_id=drive_config.drive_id,
            )

            if new_folder:
                new_folder_id = new_folder.get("id")
                if new_folder_id:
                    folder_url = (
                        f"https://drive.google.com/drive/folders/{new_folder_id}"
                    )
                    row["Ссылка на Google Drive папку клиента"] = folder_url
                    updated_count += 1
                    logger.info(
                        "Row {}: Found matching folder '{}' -> {}",
                        idx,
                        folder_name,
                        folder_url,
                    )
                else:
                    error_count += 1
                    row["Ссылка на Google Drive папку клиента"] = (
                        "error: found folder but ID is missing"
                    )
                    logger.warning("Row {}: Found folder but ID is missing", idx)
            else:
                error_count += 1
                row["Ссылка на Google Drive папку клиента"] = (
                    f"error: folder '{folder_name}' not found in new drive"
                )
                logger.warning(
                    "Row {}: Folder '{}' not found in new drive",
                    idx,
                    folder_name,
                )

        except Exception as e:
            error_count += 1
            error_msg = f"error: {str(e)}"
            row["Ссылка на Google Drive папку клиента"] = error_msg
            logger.error("Row {}: Failed to process: {}", idx, e)

        if (idx - 1) % 10 == 0:
            logger.debug("Processed {}/{} rows", idx - 1, len(rows))

    # Write updated CSV back
    logger.info("Writing updated CSV to {}", csv_file)
    csv_file.parent.mkdir(parents=True, exist_ok=True)

    with csv_file.open("w", newline="", encoding="utf-8") as csv_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    # Update contacts in Planfix if requested
    planfix_updated_count = 0
    planfix_error_count = 0

    if write_to_contacts and planfix_client:
        logger.info("Updating contacts in Planfix...")
        for idx, row in enumerate(rows, start=2):
            folder_link = (
                row.get("Ссылка на Google Drive папку клиента") or ""
            ).strip()
            contact_number = (row.get("Номер") or "").strip()

            # Skip if folder link contains "error" or is empty
            if not folder_link or "error" in folder_link.lower():
                continue

            # Skip if contact number is missing
            if not contact_number:
                logger.warning(
                    "Row {}: Skipping Planfix update, missing contact number", idx
                )
                continue

            try:
                planfix_client.update_contact(contact_number, folder_link)
                planfix_updated_count += 1
                logger.info(
                    "Row {}: Updated contact {} in Planfix", idx, contact_number
                )
            except Exception as e:
                planfix_error_count += 1
                logger.error(
                    "Row {}: Failed to update contact {} in Planfix: {}",
                    idx,
                    contact_number,
                    e,
                )

    logger.info("Migration completed:")
    logger.info("  Total rows: {}", len(rows))
    logger.info("  Updated: {}", updated_count)
    logger.info("  Skipped (already had link): {}", skipped_count)
    logger.info("  Errors: {}", error_count)
    if write_to_contacts and planfix_client:
        logger.info("  Planfix updates: {}", planfix_updated_count)
        logger.info("  Planfix errors: {}", planfix_error_count)


def run_migrate_contact_folders(args, config_data, drive_config, service) -> None:
    planfix_client = None
    if args.write_to_contacts:
        from ..config_loader import build_planfix_config
        from ..planfix_client import PlanfixClient

        planfix_config = build_planfix_config(config_data)
        planfix_client = PlanfixClient(planfix_config)

    migrate_contact_folders(
        service,
        drive_config,
        planfix_client=planfix_client,
        write_to_contacts=args.write_to_contacts,
    )
