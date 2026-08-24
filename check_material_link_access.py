#!/usr/bin/env python3
"""
Read-only: show who can open the documents from the Planfix field
"Ссылка на готовый материал".

Context: on 19.08.2026 managers reported that files attached to that field
stopped being commentable by the client automatically. The /share_file route
(triggered from Planfix) grants an `anyone` permission on the document itself,
but only the "Написание статьи в СМИ" object has that trigger (643); science
writing tasks never had it, so their documents were reachable only while the
client folder itself was open by link - and those links were revoked on 15.08.

Prints file metadata (name, parents, drive) and every permission, so the
difference between "anyone with link", "domain" and named grants is visible.

Nothing is written: only files.get and permissions.list.

Usage:
    .venv/bin/python check_material_link_access.py URL_OR_ID [URL_OR_ID ...]
    .venv/bin/python check_material_link_access.py --config data/config.yml URL
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from googleapiclient.errors import HttpError

from src.drive_audit.google_client import (
    get_file_metadata,
    get_file_permissions,
    get_service,
)
from src.drive_audit.main import load_config
from src.drive_audit.model import DriveConfig

ID_RE = re.compile(r"[-\w]{25,}")


def extract_id(value: str) -> str:
    """Pull the file id out of a Google Docs/Drive URL, or return it as is."""
    match = ID_RE.search(value)
    if not match:
        raise ValueError(f"no file id in {value!r}")
    return match.group(0)


def describe(service, raw: str) -> None:
    file_id = extract_id(raw)
    print("=" * 70)
    print(f"{raw}\n  id: {file_id}")
    try:
        meta: Dict[str, Any] = get_file_metadata(service, file_id)
    except HttpError as error:
        print(f"  metadata error: {error}")
        return
    print(f"  name:    {meta.get('name')}")
    print(f"  mime:    {meta.get('mimeType')}")
    print(f"  driveId: {meta.get('driveId')}")
    print(f"  parents: {meta.get('parents')}")
    try:
        permissions: List[Dict[str, Any]] = get_file_permissions(service, file_id)
    except HttpError as error:
        print(f"  permissions error: {error}")
        return
    if not permissions:
        print("  permissions: (none returned)")
    for perm in permissions:
        target = perm.get("emailAddress") or perm.get("domain") or perm.get("type")
        expires = perm.get("expirationTime")
        inherited = perm.get("permissionDetails")
        print(
            f"  - {perm.get('type')}: {target} role={perm.get('role')}"
            f"{' expires=' + expires if expires else ''}"
            f"{' inherited=' + str(inherited) if inherited else ''}"
        )


def summarize(service, raw: str) -> str:
    """One line per file: public / inherited / private."""
    file_id = extract_id(raw)
    try:
        permissions = get_file_permissions(service, file_id)
    except HttpError as error:
        return f"{file_id},error,{error.resp.status if hasattr(error, 'resp') else '?'}"
    anyone = [p for p in permissions if p.get("type") == "anyone"]
    if not anyone:
        return f"{file_id},none,"
    perm = anyone[0]
    details = perm.get("permissionDetails") or []
    own = any(not d.get("inherited") for d in details)
    kind = "file" if own else "inherited"
    return f"{file_id},{kind},{perm.get('role')}"


def outsiders(permissions: List[Dict[str, Any]]) -> List[str]:
    """Named grants to non-corporate accounts - the client's own access."""
    result = []
    for perm in permissions:
        email = (perm.get("emailAddress") or "").lower()
        if not email or email.endswith("@expertizeme.org") or "gserviceaccount" in email:
            continue
        result.append(f"{email}:{perm.get('role')}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*", help="document URLs or file ids")
    parser.add_argument("--config", default="data/config.yml", help="config file")
    parser.add_argument("--urls-file", default="", help="file with one URL per line")
    parser.add_argument("--summary", action="store_true", help="one CSV line per file")
    args = parser.parse_args()

    urls = list(args.urls)
    if args.urls_file:
        urls += [line.strip() for line in Path(args.urls_file).read_text().splitlines() if line.strip()]

    config_data = load_config(str(Path(args.config)))
    service = get_service(DriveConfig.from_dict(config_data))

    if args.summary:
        print("file_id,anyone,role,outsiders")
        for raw in urls:
            file_id = extract_id(raw)
            try:
                perms = get_file_permissions(service, file_id)
            except HttpError as error:
                print(f"{file_id},error,,{error}", flush=True)
                continue
            line = summarize(service, raw)
            print(f"{line},{'|'.join(outsiders(perms))}", flush=True)
        return 0

    for raw in urls:
        describe(service, raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
