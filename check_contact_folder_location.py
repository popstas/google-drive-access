"""Проверить, где лежат папки клиентов из поля Планфикса 823: на общем диске или нет.

Вход: CSV из planfix-api-client (examples/dump-contact-drive-folders.ts),
колонки contact_id, contact_name, folder_id.
Выход: тот же CSV плюс колонки location (shared / other_drive / not_found / error),
drive_id, owner, parent_id, name, trashed.

Только чтение: files.get под сервисным аккаунтом, ничего не меняется.
Сервисный аккаунт видит общий диск и всё, что открыто "по ссылке" - этого хватает,
чтобы отличить папку на общем диске от папки на чужом личном диске.

Run:
  .venv/bin/python check_contact_folder_location.py \
      --input ~/projects/js/planfix-api-client/data/contact-drive-folders.csv \
      --output data/contact-folder-location.csv
"""

import argparse
import csv
import sys

import google_auth_httplib2
import httplib2
import yaml
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
SCOPES_RW = ["https://www.googleapis.com/auth/drive"]
TIMEOUT_SEC = 30


def build_service(config_path: str, readonly: bool = True):
    with open(config_path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    creds = service_account.Credentials.from_service_account_file(
        cfg["google"]["credentials_file"], scopes=SCOPES if readonly else SCOPES_RW
    )
    http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=TIMEOUT_SEC))
    return build("drive", "v3", http=http, cache_discovery=False), cfg["drive"]["id"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default="data/contact-folder-location.csv")
    ap.add_argument("--config", default="data/config.yml")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    service, shared_drive_id = build_service(args.config)

    with open(args.input, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("folder_id")]
    if args.limit:
        rows = rows[: args.limit]
    print(f"папок к проверке: {len(rows)}", flush=True)

    extra = ["location", "drive_id", "owner", "parent_id", "name", "trashed"]
    counts: dict = {}
    with open(args.output, "w", encoding="utf-8", newline="") as out_fh:
        writer = csv.DictWriter(out_fh, fieldnames=list(rows[0].keys()) + extra)
        writer.writeheader()
        for i, row in enumerate(rows, 1):
            info = {k: "" for k in extra}
            try:
                meta = (
                    service.files()
                    .get(
                        fileId=row["folder_id"],
                        supportsAllDrives=True,
                        fields="id,name,driveId,owners(emailAddress),parents,trashed",
                    )
                    .execute(num_retries=2)
                )
                drive_id = meta.get("driveId", "")
                info.update(
                    location="shared" if drive_id == shared_drive_id else "other_drive",
                    drive_id=drive_id,
                    owner=",".join(o.get("emailAddress", "") for o in meta.get("owners", [])),
                    parent_id=",".join(meta.get("parents", [])),
                    name=meta.get("name", ""),
                    trashed=str(meta.get("trashed", False)),
                )
            except HttpError as err:
                info["location"] = "not_found" if err.resp.status == 404 else f"error_{err.resp.status}"
            except Exception as err:  # таймаут, сеть
                info["location"] = f"error_{type(err).__name__}"
            counts[info["location"]] = counts.get(info["location"], 0) + 1
            writer.writerow({**row, **info})
            if i % 100 == 0:
                print(f"  {i}/{len(rows)} {counts}", flush=True)

    print(f"итого: {counts}; файл: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
