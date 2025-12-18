import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from ..google_client import delete_permission
from ..model import DriveConfig


def _fix_scientific_notation(permission_id: str) -> str:
    """
    Convert Excel scientific notation back to full numeric string.

    Examples:
        "1,09484300468899E+019" -> "109484300468899019"
        "1.34491612254202E+017" -> "134491612254202017"

    Args:
        permission_id: Permission ID that may be in scientific notation

    Returns:
        Fixed permission ID as string, or original if not scientific notation
    """
    # Remove commas and spaces
    cleaned = permission_id.replace(",", "").replace(" ", "").strip()

    # Check if it's scientific notation (E+ or E-)
    if "E+" in cleaned.upper() or "E-" in cleaned.upper():
        try:
            # Parse as float then convert to int to get full number
            num = float(cleaned)
            # Convert to int to remove decimal, then back to string
            fixed_id = str(int(num))
            logger.debug(
                "Converted scientific notation {} to {}", permission_id, fixed_id
            )
            return fixed_id
        except (ValueError, OverflowError) as e:
            logger.warning(
                "Failed to convert scientific notation {}: {}", permission_id, e
            )
            return permission_id

    return permission_id


def _is_root_permission(row: Dict[str, str]) -> bool:
    """
    Check if a permission is a root permission (not inherited).

    Args:
        row: CSV row dictionary

    Returns:
        True if the permission is a root permission (should be deleted)
    """
    inherited = row.get("inherited", "").strip().lower()
    inherited_from_id = row.get("inherited_from_id", "").strip()

    # Root permission: inherited is False or inherited_from_id is empty
    return inherited == "false" and not inherited_from_id


def remove_access(
    service,
    drive_config: DriveConfig,
    csv_file: Path = Path("data/remove-access.csv"),
    dry_run: bool = False,
) -> None:
    """
    Remove root (non-inherited) permissions from files based on CSV data.

    Args:
        service: Google Drive service object
        drive_config: Drive configuration
        csv_file: Path to CSV file with permissions to remove (default: data/remove-access.csv)
        dry_run: If True, only show actions without executing
    """
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    logger.info("Reading CSV file from {}", csv_file)

    # Read all rows from CSV
    all_rows: List[Dict[str, str]] = []
    with csv_file.open(encoding="utf-8-sig", newline="") as csv_handle:
        reader = csv.DictReader(csv_handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV file {csv_file} has no headers")

        required_fields = {
            "file_id",
            "permission_id",
            "permission_email",
            "inherited",
            "inherited_from_id",
        }
        if not required_fields.issubset(set(reader.fieldnames)):
            raise ValueError(
                f"CSV must contain required fields {sorted(required_fields)}, "
                f"got {reader.fieldnames}"
            )

        for row in reader:
            all_rows.append(row)

    logger.info("Read {} rows from CSV", len(all_rows))

    # Filter for root permissions only
    root_permissions = [row for row in all_rows if _is_root_permission(row)]
    inherited_permissions = [row for row in all_rows if not _is_root_permission(row)]

    logger.info("Found {} root permissions (will be deleted)", len(root_permissions))
    logger.info(
        "Found {} inherited permissions (will be skipped)", len(inherited_permissions)
    )

    if not root_permissions:
        logger.info("No root permissions found to delete")
        return

    # Group by user email for statistics
    permissions_by_user: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in root_permissions:
        email = row.get("permission_email", "").strip()
        if email:
            permissions_by_user[email].append(row)
        else:
            # Handle permissions without email (domain, anyone, etc.)
            permission_type = row.get("permission_type", "").strip()
            domain = row.get("permission_domain", "").strip()
            display_name = row.get("display_name", "").strip()
            if domain:
                key = f"domain:{domain}"
            elif permission_type == "anyone":
                key = "anyone"
            else:
                key = display_name or permission_type or "unknown"
            permissions_by_user[key].append(row)

    # Display statistics
    logger.info("Users and permissions to be deleted:")
    total_permissions = 0
    for user_email, perms in sorted(permissions_by_user.items()):
        count = len(perms)
        total_permissions += count
        logger.info("  - {}: {} permission(s)", user_email, count)
    logger.info(
        "Total: {} permission(s) across {} user(s)",
        total_permissions,
        len(permissions_by_user),
    )

    if dry_run:
        logger.info("[dry-run] Would delete {} root permissions", total_permissions)
        return

    # Delete permissions
    logger.info("Deleting permissions...")
    deleted_count = 0
    not_found_count = 0
    failed_count = 0
    failed_by_user: Dict[str, int] = defaultdict(int)
    not_found_by_user: Dict[str, int] = defaultdict(int)

    for row in root_permissions:
        file_id = row.get("file_id", "").strip()
        permission_id = row.get("permission_id", "").strip()
        permission_email = row.get("permission_email", "").strip()
        file_name = row.get("file_name", "").strip()
        location = row.get("location", "").strip()

        if not file_id or not permission_id:
            logger.warning(
                "Skipping row with missing file_id or permission_id: {}",
                row,
            )
            failed_count += 1
            continue

        # Fix scientific notation if present (Excel corruption)
        original_permission_id = permission_id
        permission_id = _fix_scientific_notation(permission_id)
        if permission_id != original_permission_id:
            logger.info(
                "Fixed permission_id from {} to {} for file {} ({})",
                original_permission_id,
                permission_id,
                file_name or file_id,
                location or file_id,
            )

        user_key = permission_email or f"file:{file_id}"
        logger.debug(
            "Deleting permission {} from file {} ({})",
            permission_id,
            file_name or file_id,
            location or file_id,
        )

        try:
            result = delete_permission(service, file_id, permission_id)
            if result == "deleted":
                deleted_count += 1
                logger.info(
                    "Deleted permission {} from file {} ({})",
                    permission_id,
                    file_name or file_id,
                    location or file_id,
                )
            elif result == "not_found":
                not_found_count += 1
                not_found_by_user[user_key] += 1
                logger.debug(
                    "Permission {} not found on file {} ({}), skipping",
                    permission_id,
                    file_name or file_id,
                    location or file_id,
                )
        except Exception as e:
            logger.error(
                "Failed to delete permission {} from file {} ({}): {}",
                permission_id,
                file_name or file_id,
                location or file_id,
                e,
            )
            failed_count += 1
            failed_by_user[user_key] += 1

    logger.info("Summary:")
    logger.info("  Successfully deleted: {} permission(s)", deleted_count)
    if not_found_count > 0:
        logger.info("  Not found (already deleted?): {} permission(s)", not_found_count)
    if failed_count > 0:
        logger.info("  Failed: {} permission(s)", failed_count)
    if not_found_by_user:
        logger.info("  Not found by user:")
        for user, count in sorted(not_found_by_user.items()):
            logger.info("    - {}: {} not found", user, count)
    if failed_by_user:
        logger.info("  Failed by user:")
        for user, count in sorted(failed_by_user.items()):
            logger.info("    - {}: {} failed", user, count)


def run_remove_access(args, config_data, drive_config, service) -> None:
    command_config = config_data.get("commands", {}).get("remove_access", {})
    csv_file = (
        args.csv_file or command_config.get("csv_file") or "data/remove-access.csv"
    )
    remove_access(
        service,
        drive_config,
        csv_file=Path(csv_file),
        dry_run=args.dry_run,
    )
