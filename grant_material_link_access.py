#!/usr/bin/env python3
"""
Open link access on documents from the Planfix field "Ссылка на готовый материал".

The Planfix scenarios (643 for media writing, 1451/1453/1455 added 24.08.2026 for
science writing, translations and recommender search) only fire when the field
changes, so documents attached before those scenarios existed stay unreachable
for the client. This script walks the backlog exported by
`audit-material-link-open-tasks.ts` in planfix-api-client and grants the missing
`anyone` permission with the commenter role.

Safety rules:

* documents only - a link pointing at a folder is skipped, because opening whole
  client folders by link is exactly the leak closed on 15.08.2026;
* files outside the shared drive are skipped (nothing to grant there);
* a file that already has any `anyone` permission, inherited or its own, is left
  alone;
* preview by default, writes only with --apply.

Inputs:
    --csv   export with columns task_id, object, status, link (task_name optional)

Outputs:
    data/grant-material-link-access.csv  - audit log, one row per document

Usage:
    .venv/bin/python grant_material_link_access.py --csv ../../js/planfix-api-client/data/material-link-open-tasks.csv
    .venv/bin/python grant_material_link_access.py --csv <path> --apply
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from googleapiclient.errors import HttpError
from loguru import logger

from src.drive_audit.google_client import (
    create_anyone_permission,
    get_file_permissions,
    get_service,
)
from src.drive_audit.logger_config import configure_logger
from src.drive_audit.main import load_config
from src.drive_audit.model import DriveConfig

ID_RE = re.compile(r"[-\w]{25,}")


def item_meta(service, file_id: str) -> Dict[str, Any]:
    """Name, kind and home drive in one call - get_item_info drops driveId."""
    return (
        service.files()
        .get(fileId=file_id, supportsAllDrives=True, fields="id, name, mimeType, driveId")
        .execute()
    )
FOLDER_MIME = "application/vnd.google-apps.folder"
LOG_COLUMNS = ["file_id", "task_id", "object", "status", "name", "action", "details"]


def extract_id(value: str) -> str:
    match = ID_RE.search(value or "")
    if not match:
        raise ValueError(f"no file id in {value!r}")
    return match.group(0)


def load_rows(csv_file: Path) -> List[Dict[str, str]]:
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")
    with csv_file.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "link" not in reader.fieldnames:
            raise ValueError(f"CSV file {csv_file} has no link column")
        return list(reader)


def dedupe(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """One row per document: the same file can hang on several tasks."""
    seen: Dict[str, Dict[str, str]] = {}
    for row in rows:
        try:
            file_id = extract_id(row.get("link", ""))
        except ValueError:
            logger.warning("Skipping row without file id: {}", row.get("link"))
            continue
        row["file_id"] = file_id
        seen.setdefault(file_id, row)
    return list(seen.values())


def run(csv_file: Path, apply: bool, role: str, pause: float, log_file: Path, config_file: Path) -> None:
    rows = dedupe(load_rows(csv_file))
    logger.info("Documents to check: {}", len(rows))

    config_data = load_config(str(config_file))
    drive_config = DriveConfig.from_dict(config_data)
    service = get_service(drive_config)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    handle = log_file.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS)
    writer.writeheader()
    counters: Dict[str, int] = {}

    def record(row: Dict[str, str], action: str, details: str = "", name: str = "") -> None:
        counters[action] = counters.get(action, 0) + 1
        writer.writerow(
            {
                "file_id": row["file_id"],
                "task_id": row.get("task_id", ""),
                "object": row.get("object", ""),
                "status": row.get("status", ""),
                "name": name,
                "action": action,
                "details": details,
            }
        )
        handle.flush()

    for index, row in enumerate(rows, 1):
        file_id = row["file_id"]
        try:
            info: Dict[str, Any] = item_meta(service, file_id)
        except HttpError as error:
            status = getattr(getattr(error, "resp", None), "status", "?")
            logger.warning("{}/{} {}: metadata error {}", index, len(rows), file_id, status)
            record(row, "metadata_error", str(status))
            continue

        name = info.get("name", "")
        if info.get("mimeType") == FOLDER_MIME:
            logger.info("{}/{} {}: folder, skipped", index, len(rows), name)
            record(row, "skip_folder", "link points at a folder", name)
            continue

        if info.get("driveId") != drive_config.drive_id:
            logger.info("{}/{} {}: outside the shared drive, skipped", index, len(rows), name)
            record(row, "skip_outside_drive", "file lives outside the corporate drive", name)
            continue

        try:
            permissions = get_file_permissions(service, file_id)
        except HttpError as error:
            status = getattr(getattr(error, "resp", None), "status", "?")
            logger.warning("{}/{} {}: permissions error {}", index, len(rows), name, status)
            record(row, "permissions_error", str(status), name)
            continue

        anyone = next((p for p in permissions if p.get("type") == "anyone"), None)
        if anyone:
            logger.info("{}/{} {}: already public ({})", index, len(rows), name, anyone.get("role"))
            record(row, "already_public", str(anyone.get("role")), name)
            continue

        if not apply:
            logger.info("{}/{} {}: would grant anyone:{}", index, len(rows), name, role)
            record(row, "would_grant", role, name)
            continue

        try:
            create_anyone_permission(service, file_id, role, None)
        except HttpError as error:
            status = getattr(getattr(error, "resp", None), "status", "?")
            logger.warning("{}/{} {}: grant failed {}", index, len(rows), name, status)
            record(row, "grant_failed", str(status), name)
            continue

        logger.info("{}/{} {}: granted anyone:{}", index, len(rows), name, role)
        record(row, "granted", role, name)
        time.sleep(pause)

    handle.close()
    logger.info("Done: {}", counters)
    logger.info("Log: {}", log_file)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="export from audit-material-link-open-tasks.ts")
    parser.add_argument("--apply", action="store_true", help="actually grant permissions")
    parser.add_argument("--role", default="commenter", help="role for the anyone permission")
    parser.add_argument("--pause", type=float, default=0.2, help="pause between writes, seconds")
    parser.add_argument("--log", default="data/grant-material-link-access.csv", help="audit log path")
    parser.add_argument("--config", default="data/config.yml", help="config file")
    args = parser.parse_args()

    configure_logger()
    run(Path(args.csv), args.apply, args.role, args.pause, Path(args.log), Path(args.config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
