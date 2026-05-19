"""
Find direct (inherited=False) author access on client folders that are NOT present
in the active-science-articles list at all.

This is a subset of the previous extra-access set: only folders that have *no*
current task assignment. Authors on such folders should not retain access.

Output:
    data/remove-access-inactive-folders.csv
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

DATA = Path("data")
SCIENCE_EMAILS = DATA / "science_emails.csv"
ACTIVE_ARTICLES = DATA / "2026-05-18-active_science_articles.csv"
PERMISSIONS = DATA / "permissions.csv"
OUTPUT = DATA / "remove-access-inactive-folders.csv"

PERMISSION_COLUMNS = [
    "file_id",
    "file_name",
    "location",
    "client_name",
    "permission_id",
    "permission_type",
    "permission_role",
    "permission_email",
    "permission_domain",
    "display_name",
    "allow_file_discovery",
    "expiration",
    "deleted",
    "inherited",
    "inherited_from_id",
    "inherited_from_location",
]


def load_authors() -> set[str]:
    with SCIENCE_EMAILS.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return {row["email"].strip().lower() for row in reader if row.get("email")}


def extract_folder_id(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    path = urlparse(url).path
    marker = "/folders/"
    idx = path.find(marker)
    if idx == -1:
        return ""
    return path[idx + len(marker):].split("/")[0].strip()


def load_active_folder_ids() -> set[str]:
    ids: set[str] = set()
    with ACTIVE_ARTICLES.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            fid = extract_folder_id(row.get("Google Drive клиента", ""))
            if fid:
                ids.add(fid)
    return ids


def is_client_folder_row(location: str) -> bool:
    if not location.startswith("/"):
        return False
    return location.count("/") == 1 and len(location) > 1


def main() -> None:
    authors = load_authors()
    active_folders = load_active_folder_ids()

    rows: list[dict] = []
    distinct_inactive_folders_with_author: set[str] = set()
    distinct_inactive_folders_seen: set[str] = set()

    with PERMISSIONS.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not is_client_folder_row(row.get("location", "")):
                continue
            file_id = row.get("file_id", "").strip()
            if file_id in active_folders:
                continue
            distinct_inactive_folders_seen.add(file_id)

            if row.get("inherited", "").strip().lower() != "false":
                continue
            if row.get("permission_type", "").strip() != "user":
                continue
            email = row.get("permission_email", "").strip().lower()
            if email not in authors:
                continue

            rows.append(row)
            distinct_inactive_folders_with_author.add(file_id)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PERMISSION_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in PERMISSION_COLUMNS})

    print(f"Authors loaded:                                   {len(authors)}")
    print(f"Active folder IDs (from articles CSV):            {len(active_folders)}")
    print(f"Inactive client folders seen in permissions.csv:  {len(distinct_inactive_folders_seen)}")
    print(f"  of those with at least one author access:       {len(distinct_inactive_folders_with_author)}")
    print(f"Author rows -> {OUTPUT}:  {len(rows)}")

    if rows:
        per_author = Counter(r["permission_email"].strip().lower() for r in rows)
        print("\nRows per author:")
        for email, count in sorted(per_author.items(), key=lambda kv: -kv[1]):
            print(f"  {count:5d}  {email}")


if __name__ == "__main__":
    main()
