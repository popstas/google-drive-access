# move_files_to_public_folder — auto-move files into the client's public subfolder

## Purpose

For each first-level client folder, move files whose name and MIME type match the configured regex/MIME lists into the client's `public` subfolder (auto-created if missing, granted "anyone with the link → reader"). Typical use: bulk-publish KP/Media-plan spreadsheets.

## When to use

- After an audit shows public files sitting at the client folder root instead of inside `public_subdir`.
- Bulk-publishing a known class of files (e.g. spreadsheet KPs) across many clients.

## Inputs

Config (`data/config.yml`):

```yaml
commands:
  move_files_to_public_folder:
    file_match:
      - ".*?KP.*?"
      - "^Public Report\\.csv$"
    mimeType_match:
      - "application/vnd.google-apps.spreadsheet"
      - "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
scan:
  public_subdir: "public"
```

A file is moved only if it matches **both** a `file_match` regex **and** (if set) one of `mimeType_match`.

CLI flags:

- `--config <path>`
- `--dry-run` — preview only, no Drive mutations
- `--debug`

## Command line

```bash
# Always start with dry-run
python -m drive_audit.commands --config data/config.yml move_files_to_public_folder --dry-run

# Apply
python -m drive_audit.commands --config data/config.yml move_files_to_public_folder
```

## Outputs

| Artefact | Description |
|----------|-------------|
| `data/move_files_to_public_folder.log` | Operation log |
| Google Drive | Matched files moved into `<client>/<public_subdir>/`; new public subfolder created with link-share when needed |

## Pitfalls

- Always do a `--dry-run` first — a broad regex affects hundreds of files.
- Only files at depth 2 (directly inside a client folder) are considered — nested files are skipped.
- Hitting Google API rate limits on large drives — re-run after a backoff if the log shows 429s.
- Service account must have write/manage permissions on the Shared Drive.
