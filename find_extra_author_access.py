"""
Identify author access to client folders that is not justified by an active task.

Inputs:
    data/science_emails.csv                       - active author emails
    data/2026-05-18-active_science_articles.csv   - (client folder URL, executor email) pairs
    data/permissions.csv                          - exported drive permissions

Outputs:
    data/remove-access.csv               - author rows to delete (consumed by `remove_access`)
    data/non-author-client-access.csv    - non-author emails with direct access to client folders
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
REMOVE_ACCESS = DATA / "remove-access.csv"
NON_AUTHOR_ACCESS = DATA / "non-author-client-access.csv"

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


def load_active_pairs() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    with ACTIVE_ARTICLES.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            folder_id = extract_folder_id(row.get("Google Drive клиента", ""))
            exec_email = row.get("Google аккаунт исполнителя", "").strip().lower()
            if folder_id and exec_email:
                pairs.add((folder_id, exec_email))
    return pairs


def is_client_folder_row(location: str) -> bool:
    if not location.startswith("/"):
        return False
    return location.count("/") == 1 and len(location) > 1


def main() -> None:
    authors = load_authors()
    active_pairs = load_active_pairs()
    active_folders = {folder for folder, _ in active_pairs}

    extra_rows: list[dict] = []
    non_author_rows: list[dict] = []

    client_folder_seen = 0
    direct_seen = 0
    skipped_non_user = 0
    skipped_empty_email = 0

    with PERMISSIONS.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not is_client_folder_row(row.get("location", "")):
                continue
            client_folder_seen += 1
            if row.get("inherited", "").strip().lower() != "false":
                continue
            direct_seen += 1
            if row.get("permission_type", "").strip() != "user":
                skipped_non_user += 1
                continue
            email = row.get("permission_email", "").strip().lower()
            if not email:
                skipped_empty_email += 1
                continue

            file_id = row.get("file_id", "").strip()
            if email in authors:
                if (file_id, email) not in active_pairs:
                    extra_rows.append(row)
            else:
                non_author_rows.append(row)

    _write(REMOVE_ACCESS, extra_rows)
    _write(NON_AUTHOR_ACCESS, non_author_rows)

    print(f"Authors loaded:                              {len(authors)}")
    print(f"Active (folder, executor) pairs:             {len(active_pairs)}")
    print(f"Distinct active folders:                     {len(active_folders)}")
    print(f"Client-folder rows scanned:                  {client_folder_seen}")
    print(f"Direct (inherited=False) rows:               {direct_seen}")
    print(f"Skipped non-user (anyone/domain/group):      {skipped_non_user}")
    print(f"Skipped empty email:                         {skipped_empty_email}")
    print(f"Extra AUTHOR rows -> {REMOVE_ACCESS}:        {len(extra_rows)}")
    print(f"Non-author rows -> {NON_AUTHOR_ACCESS}:      {len(non_author_rows)}")

    if extra_rows:
        per_author = Counter(r["permission_email"].strip().lower() for r in extra_rows)
        print("\nExtra rows per author:")
        for email, count in sorted(per_author.items(), key=lambda kv: -kv[1]):
            print(f"  {count:5d}  {email}")

    if non_author_rows:
        per_non_author = Counter(
            r["permission_email"].strip().lower() for r in non_author_rows
        )
        print(f"\nDistinct non-author emails: {len(per_non_author)} (top 20):")
        for email, count in per_non_author.most_common(20):
            print(f"  {count:5d}  {email}")


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PERMISSION_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in PERMISSION_COLUMNS})


if __name__ == "__main__":
    main()
