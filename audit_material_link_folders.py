#!/usr/bin/env python3
"""
Read-only: describe the folders that sit in the Planfix field
"Ссылка на готовый материал".

/share_file refuses folder links since 24.08.2026, so those tasks stay without
client access. Before automating folder access we need to know what these
folders actually are: where they live, how deep under the client folder they
sit, and whether they are already open by link.

Input is the CSV produced by audit-material-link-open-tasks.ts in
planfix-api-client. Nothing is written: files.get and permissions.list only.

Usage:
    .venv/bin/python audit_material_link_folders.py --csv <path>
    .venv/bin/python audit_material_link_folders.py --csv <path> --out data/material-link-folders.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from googleapiclient.errors import HttpError
from loguru import logger

from src.drive_audit.google_client import get_file_permissions, get_service
from src.drive_audit.logger_config import configure_logger
from src.drive_audit.main import load_config
from src.drive_audit.model import DriveConfig

ID_RE = re.compile(r"[-\w]{25,}")
FOLDER_MIME = "application/vnd.google-apps.folder"
COLUMNS = ["task_id", "object", "status", "folder_id", "name", "in_drive", "depth", "path", "anyone", "anyone_own"]


def meta(service, file_id: str) -> Dict[str, Any]:
    return (
        service.files()
        .get(fileId=file_id, supportsAllDrives=True, fields="id, name, mimeType, driveId, parents")
        .execute()
    )


def ancestry(service, info: Dict[str, Any], drive_id: str, limit: int = 8) -> List[str]:
    """Folder names from the item up to the drive root, nearest parent first."""
    names: List[str] = []
    parents = info.get("parents") or []
    for _ in range(limit):
        if not parents:
            break
        parent_id = parents[0]
        if parent_id == drive_id:
            names.append("<корень диска>")
            break
        try:
            parent = meta(service, parent_id)
        except HttpError:
            names.append("<нет доступа>")
            break
        names.append(parent.get("name", "?"))
        parents = parent.get("parents") or []
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="export from audit-material-link-open-tasks.ts")
    parser.add_argument("--out", default="data/material-link-folders.csv", help="where to write the report")
    parser.add_argument("--config", default="data/config.yml", help="config file")
    args = parser.parse_args()

    configure_logger()
    config_data = load_config(str(Path(args.config)))
    drive_config = DriveConfig.from_dict(config_data)
    service = get_service(drive_config)

    rows = list(csv.DictReader(Path(args.csv).open(encoding="utf-8-sig", newline="")))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    handle = out_path.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=COLUMNS)
    writer.writeheader()

    seen = set()
    folders = 0

    for row in rows:
        match = ID_RE.search(row.get("link", ""))
        if not match or match.group(0) in seen:
            continue
        file_id = match.group(0)
        seen.add(file_id)
        try:
            info = meta(service, file_id)
        except HttpError:
            continue
        if info.get("mimeType") != FOLDER_MIME:
            continue
        folders += 1

        in_drive = info.get("driveId") == drive_config.drive_id
        path = ancestry(service, info, drive_config.drive_id) if in_drive else []
        anyone: Optional[Dict[str, Any]] = None
        try:
            perms = get_file_permissions(service, file_id)
            anyone = next((p for p in perms if p.get("type") == "anyone"), None)
        except HttpError:
            perms = []

        own = ""
        if anyone:
            details = anyone.get("permissionDetails") or []
            own = "file" if any(not d.get("inherited") for d in details) else "inherited"

        writer.writerow(
            {
                "task_id": row.get("task_id", ""),
                "object": row.get("object", ""),
                "status": row.get("status", ""),
                "folder_id": file_id,
                "name": info.get("name", ""),
                "in_drive": "yes" if in_drive else "no",
                "depth": len(path),
                "path": " / ".join(reversed(path)),
                "anyone": (anyone or {}).get("role", ""),
                "anyone_own": own,
            }
        )
        handle.flush()
        logger.info("{}: {} (в диске: {}, путь: {})", file_id, info.get("name"), in_drive, " / ".join(reversed(path)))

    handle.close()
    logger.info("Папок разобрано: {}. Отчёт: {}", folders, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
