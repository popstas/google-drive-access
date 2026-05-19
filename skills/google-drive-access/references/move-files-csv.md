# move_files_csv — move files according to an explicit CSV manifest

## Purpose

Move a hand-picked set of files to specific destination folders by ID. Use when `move_files_to_public_folder`'s regex/MIME rules aren't precise enough — e.g. each file has a different destination folder.

## When to use

- Routing a "pending" inbox folder full of proposals into per-client folders.
- Post-audit cleanup with a manually curated `file_id` → `dest_folder` mapping.

## Inputs

Manifest CSV (UTF-8 with BOM supported):

| Column | Required | Description |
|--------|----------|-------------|
| `file_name` | yes | For logs only; rows where `file_name` starts with `#` are skipped |
| `file_id` | yes | Drive file ID |
| `dest_folder` | yes | Drive folder ID to move into |
| `source_folder` | no | Source folder ID for operator sanity-check |

Example (anonymized):

```csv
file_name,file_id,dest_folder,source_folder
KP Example.xlsx,<FILE_ID>,<DEST_FOLDER_ID>,<SOURCE_FOLDER_ID>
```

Config (`data/config.yml`):

```yaml
commands:
  move_files_csv:
    csv_file: "data/move_files.csv"
```

CLI flags:

- `--csv-file <path>` — overrides config (default falls back to the config value)
- `--dry-run`
- `--debug`

## Command line

```bash
python -m drive_audit.commands --config data/config.yml move_files_csv --dry-run
python -m drive_audit.commands --config data/config.yml move_files_csv \
  --csv-file data/move_files.csv
```

## Outputs

| Artefact | Description |
|----------|-------------|
| `data/move_files_csv.log` | Operation log |
| Google Drive | Files moved into the destination folders listed in the manifest |

## Pitfalls

- A wrong `dest_folder` silently moves the file to the wrong client — verify `source_folder` and `file_name` before running without `--dry-run`.
- This command does **not** create or share a public subfolder; if you want public access on the destination, pair with `move_files_to_public_folder` or set sharing manually.
- Rows missing `file_id` or `dest_folder` log a warning and are skipped.
