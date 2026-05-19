# delete_empty_folders — prune empty depth-1 client folders

## Purpose

Delete first-level client folders that contain no files anywhere in their subtree (only nested empty folders). Driven by a `files.csv` snapshot, not a live Drive walk.

## When to use

- Cleanup after `merge_client_folders` left empty shells behind.
- General drive hygiene before a final `compare_files`.

## Inputs

CLI flags:

| Flag | Description |
|------|-------------|
| `--csv-file <path>` | File-structure CSV (default `data/files.csv`) |
| `--dry-run` | Show what would be deleted; no Drive mutations |
| `--config <path>` | Config (Drive auth) |
| `--debug` | Verbose logging |

## Command line

```bash
python -m drive_audit.commands --config data/config.yml delete_empty_folders --dry-run
python -m drive_audit.commands --config data/config.yml delete_empty_folders \
  --csv-file data/files.csv
```

## Outputs

| Artefact | Description |
|----------|-------------|
| `data/delete_empty_folders.log` | Per-folder deletion log |
| Google Drive | Empty depth-1 folders removed |

## Pitfalls

- Deletion is irreversible — only run after a `--dry-run` and a manual scan of the list.
- A stale CSV can flag a non-empty folder as empty (files added since the export). Always rerun `audit-scan` immediately before applying.
- Service account needs delete rights on the Shared Drive.
