# revert_merge_client_folders.py — undo a `merge_client_folders` run

## Purpose

Move files back to their original parents after a `merge_client_folders` operation. Reads the CSV log that the merge command wrote and replays each move in reverse through the Google Drive API.

## When to use

- The merge picked the wrong duplicates and files ended up under the wrong client folder.
- Need to roll back partially so the merge can be re-run with different rules.
- Recovery after an accidental production merge.

## Inputs

CLI flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--csv-file <path>` | `data/merge_client_folders.csv` | CSV log produced by the original merge. Required columns: `action`, `file_id`, `dest_folder_id`, and at least one of `source_parent_id` / `source_folder_id`. `file_name` is optional (used only for log messages). The merge CSV also contains `action == "delete"` rows; only `action == "move"` rows are processed by revert |
| `--config <path>` | `data/config.yml` | Config with service account and `drive_id` |
| `--dry-run` | off | Log intended moves only — no API mutations |
| `--debug` | off | DEBUG-level logging |

Service account must have `files.update` on the Shared Drive (`supportsAllDrives=True` is set internally).

## Command line

```bash
# Dry-run first — confirm targets and ordering
.venv/bin/python revert_merge_client_folders.py --dry-run

# Real revert
.venv/bin/python revert_merge_client_folders.py

# Non-default paths
.venv/bin/python revert_merge_client_folders.py \
  --csv-file data/merge_client_folders.csv \
  --config data/config.yml \
  --debug
```

## Outputs

| Artifact | Description |
|----------|-------------|
| `data/revert_merge_client_folders.log` | Full loguru log of each operation |
| Google Drive | Files moved back to `source_parent_id` (preferred) or `source_folder_id` (fallback) |
| stdout | Summary: total operations / reverted / errors |

## Behavior notes

- Per-row destination: prefers `source_parent_id` (the precise original parent, possibly a nested subfolder); falls back to `source_folder_id` (the client root).
- Operations run **in reverse order** of the CSV so nested moves untangle correctly.
- Per-file safety checks before moving:
  - already in the revert destination → skip with info log;
  - not in the expected `dest_folder_id` → warn but still attempt the move;
  - file has no parents → skip with warning.
- Individual failures count toward `error_count` and do not abort the loop.

## Pitfalls

- **Always run `--dry-run` first.** A merge CSV with swapped `source_folder_id` / `dest_folder_id` will scatter files into the wrong folders on revert.
- The script does **not** restore folders the original merge deleted (e.g. emptied source folders). Recreate them by hand or by re-running `audit-scan` then a corrective move.
- Permissions added to the merged destination folder after the merge are not touched.
- Rows missing `file_id`, `dest_folder_id`, or both source folder IDs (`source_parent_id` *and* `source_folder_id` empty) are silently skipped at read time — they will not appear in the log.
