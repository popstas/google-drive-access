"""Перечислить подпапки одной папки под сервисным аккаунтом (только чтение).

Нужно для папок вне общего диска, например личной папки менеджера с клиентами.
Если сервисному аккаунту папка не расшарена, список будет пустым или 404.

Run:
  .venv/bin/python list_folder_children.py --folder <id> --output data/folder-children.csv
"""

import argparse
import csv
import sys

from googleapiclient.errors import HttpError

from check_contact_folder_location import build_service

MAX_PAGES = 50


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--output", default="data/folder-children.csv")
    ap.add_argument("--config", default="data/config.yml")
    ap.add_argument("--recursive", action="store_true", help="обойти всё дерево, в выход добавить top_folder")
    args = ap.parse_args()

    service, _ = build_service(args.config)
    try:
        meta = service.files().get(
            fileId=args.folder, supportsAllDrives=True,
            fields="id,name,driveId,owners(emailAddress),capabilities(canListChildren)",
        ).execute(num_retries=2)
        print(f"папка: {meta}", flush=True)
    except HttpError as err:
        print(f"папка недоступна: HTTP {err.resp.status}", flush=True)
        return 1

    rows = []
    # очередь (папка, папка верхнего уровня); верхний уровень - сам ребёнок корня
    queue = [(args.folder, "")]
    while queue:
        folder, top = queue.pop()
        before = len(rows)
        list_children(service, folder, top, rows)
        if args.recursive:
            for r in rows[before:]:
                if r[2] == "application/vnd.google-apps.folder":
                    queue.append((r[0], top or r[0]))
        print(f"  всего {len(rows)}, в очереди {len(queue)}", flush=True)

    with open(args.output, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["folder_id", "name", "mime_type", "created", "modified", "owner", "top_folder"])
        w.writerows(rows)
    print(f"итого {len(rows)}; файл: {args.output}", flush=True)
    return 0


def list_children(service, folder, top, rows):
    token = None
    for _ in range(MAX_PAGES):
        resp = service.files().list(
            q=f"'{folder}' in parents and trashed = false",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
            fields="nextPageToken, files(id,name,mimeType,createdTime,modifiedTime,owners(emailAddress))",
            pageSize=1000, pageToken=token,
        ).execute(num_retries=2)
        for f in resp.get("files", []):
            rows.append([f["id"], f["name"], f["mimeType"], f.get("createdTime", ""),
                         f.get("modifiedTime", ""),
                         ",".join(o.get("emailAddress", "") for o in f.get("owners", [])),
                         top or f["id"]])
        token = resp.get("nextPageToken")
        if not token:
            break


if __name__ == "__main__":
    sys.exit(main())
