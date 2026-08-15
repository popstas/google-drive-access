#!/usr/bin/env python3
"""
Close public link access on client folders, one folder at a time.

For every row of the mapping CSV (folder -> Planfix contact, produced by
`map-public-drive-folders.ts` in planfix-api-client) the script:

    1. grants the contact's email a named `commenter` permission, unless it
       already has one;
    2. only then removes the `anyone` permission from the folder.

The order matters: for most clients the public link is the only way into their
own folder, so revoking it before the named grant locks them out. A folder is
never closed when the grant failed.

Preview by default; pass --apply to actually write. Wave 1 is the gmail-only
subset, hence --gmail-only being on by default: a named Drive permission works
on a Google account, and a gmail address is one.

Inputs:
    --csv     mapping CSV with columns folder_id, contact_email
              (drive_client_name, contact_name, contact_id are used for logs)

Outputs:
    data/close-public-client-folders.csv  - audit log, one row per folder
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from src.drive_audit.google_client import (
    add_user_permission,
    delete_permission,
    get_file_permissions,
    get_service,
)
from src.drive_audit.logger_config import configure_logger
from src.drive_audit.main import load_config
from src.drive_audit.model import DriveConfig

LOG_COLUMNS = [
    "folder_id",
    "client_name",
    "contact_id",
    "email",
    "grant",
    "revoke",
    "status",
    "details",
]


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def row_emails(row: Dict[str, str], gmail_only: bool) -> List[str]:
    """
    Addresses to grant for one folder.

    The Planfix field is free text: it holds one address, several separated by
    commas, or an address with junk glued to it. Pull out every address-looking
    token instead of trusting the raw string.

    In gmail-only mode the non-gmail addresses are dropped rather than granted:
    a named Drive permission needs a Google account, and a failed grant would
    keep the public link in place for the whole folder.
    """
    found = EMAIL_RE.findall(row.get("contact_email") or "")
    emails = []
    for email in found:
        email = email.lower()
        if gmail_only and not email.endswith("@gmail.com"):
            continue
        if email not in emails:
            emails.append(email)
    return emails


def load_rows(csv_file: Path, gmail_only: bool) -> List[Dict[str, str]]:
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    with csv_file.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "folder_id" not in reader.fieldnames:
            raise ValueError(f"CSV file {csv_file} has no folder_id column")
        rows = list(reader)

    selected = []
    for row in rows:
        if not (row.get("folder_id") or "").strip():
            continue
        if not row_emails(row, gmail_only):
            continue
        selected.append(row)

    logger.info(
        "Rows: {} in CSV, {} selected{}",
        len(rows),
        len(selected),
        " (gmail only)" if gmail_only else "",
    )
    return selected


def close_public_client_folders(
    csv_file: Path,
    apply: bool,
    gmail_only: bool,
    limit: int,
    role: str,
    pause: float,
    log_file: Path,
    config_file: Path,
) -> None:
    rows = load_rows(csv_file, gmail_only)
    if limit > 0:
        rows = rows[:limit]
        logger.info("Limited to {} folders", len(rows))
    if not rows:
        logger.info("Nothing to do")
        return

    config_data = load_config(str(config_file))
    drive_config = DriveConfig.from_dict(config_data)
    service = get_service(drive_config)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    handle = log_file.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS)
    writer.writeheader()

    counters: Dict[str, int] = {}

    def record(row: Dict[str, str], **fields: Any) -> None:
        counters[fields["status"]] = counters.get(fields["status"], 0) + 1
        writer.writerow(
            {
                "folder_id": row.get("folder_id", ""),
                "client_name": row.get("drive_client_name", ""),
                "contact_id": row.get("contact_id", ""),
                "email": " ".join(row_emails(row, gmail_only)),
                "grant": fields.get("grant", ""),
                "revoke": fields.get("revoke", ""),
                "status": fields["status"],
                "details": fields.get("details", ""),
            }
        )
        handle.flush()

    try:
        for index, row in enumerate(rows, start=1):
            folder_id = row["folder_id"].strip()
            emails = row_emails(row, gmail_only)
            label = f"[{index}/{len(rows)}] {folder_id} {' '.join(emails)}"

            permissions = get_file_permissions(service, folder_id)
            anyone = [p for p in permissions if p.get("type") == "anyone"]
            named = {
                (p.get("emailAddress") or "").lower()
                for p in permissions
                if p.get("type") == "user"
            }
            missing = [email for email in emails if email not in named]

            if not anyone:
                logger.info("{} - already closed, skipping", label)
                record(row, grant="skip", revoke="skip", status="already_closed")
                continue

            # 1. Named access first, for every address on the card. The link is
            #    dropped only when all of them landed - one client per folder is
            #    the common case, but a shared card may list two people.
            if not missing:
                grant = "existing"
            elif not apply:
                grant = "would_grant"
            else:
                failed_grant = ""
                for email in missing:
                    try:
                        add_user_permission(service, folder_id, email, role)
                    except Exception as error:  # pylint: disable=broad-except
                        failed_grant = f"{email}: {error}"
                        logger.error("{} - grant failed: {}", label, error)
                        break
                if failed_grant:
                    record(
                        row,
                        grant="error",
                        revoke="skip",
                        status="grant_failed",
                        details=failed_grant,
                    )
                    continue
                grant = f"granted:{len(missing)}"

            # 2. Only now drop the public link.
            if not apply:
                logger.info(
                    "{} - named access {}, would remove {} anyone permission(s)",
                    label,
                    "already there" if not missing else f"to grant ({len(missing)})",
                    len(anyone),
                )
                record(row, grant=grant, revoke="would_revoke", status="preview")
                continue

            removed = 0
            failed = ""
            for permission in anyone:
                try:
                    delete_permission(service, folder_id, permission["id"])
                    removed += 1
                except Exception as error:  # pylint: disable=broad-except
                    failed = str(error)
                    logger.error("{} - revoke failed: {}", label, error)
                    break

            if failed:
                record(
                    row,
                    grant=grant,
                    revoke="error",
                    status="revoke_failed",
                    details=failed,
                )
            else:
                logger.info("{} - {}, link removed ({})", label, grant, removed)
                record(row, grant=grant, revoke="revoked", status="closed")

            if pause:
                time.sleep(pause)
    finally:
        handle.close()

    logger.info("=" * 60)
    logger.info("Done, log: {}", log_file)
    for status, count in sorted(counters.items()):
        logger.info("  {}: {}", status, count)
    logger.info("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grant named access to clients and drop the public link on their folders"
    )
    parser.add_argument(
        "--csv",
        default="data/public-drive-folders-contacts.csv",
        help="mapping CSV: folder_id + contact_email",
    )
    parser.add_argument(
        "--config", default="data/config.yml", help="Path to configuration file"
    )
    parser.add_argument(
        "--log",
        default="data/close-public-client-folders.csv",
        help="Where to write the audit log",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually grant and revoke; without it the run is a preview",
    )
    parser.add_argument(
        "--all-emails",
        action="store_true",
        help="Do not restrict to gmail addresses (wave 1 is gmail only)",
    )
    parser.add_argument("--role", default="commenter", help="Role for the client")
    parser.add_argument("--limit", type=int, default=0, help="Max folders, 0 for all")
    parser.add_argument(
        "--pause", type=float, default=0.2, help="Seconds between folders"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    configure_logger(
        log_level="DEBUG" if args.debug else "INFO",
        log_file_path=Path("data") / "close_public_client_folders.log",
    )
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        close_public_client_folders(
            csv_file=Path(args.csv),
            apply=args.apply,
            gmail_only=not args.all_emails,
            limit=args.limit,
            role=args.role,
            pause=args.pause,
            log_file=Path(args.log),
            config_file=Path(args.config),
        )
    except Exception as error:  # pylint: disable=broad-except
        logger.error("Failed: {}", error)
        sys.exit(1)


if __name__ == "__main__":
    main()
