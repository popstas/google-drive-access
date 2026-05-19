# merge_client_folders — merge duplicate client folders at depth=1

## Purpose

Detect duplicate first-level folders (same client name appearing twice under the root) and consolidate them: move all files into one "canonical" folder, then delete the now-empty duplicates.

## When to use

- After a drive migration left two folders per client (e.g. case-/spacing-different duplicates).
- Before `delete_empty_folders` and a final `compare_files` to close out a migration.

## Inputs

CLI flags:

| Flag | Description |
|------|-------------|
| `--csv-file <path>` | Full file structure CSV (default `data/new_disk/new_files.csv`) |
| `--dry-run` | Log the merge plan without touching Drive |
| `--config <path>` | Config (Drive auth) |
| `--debug` | Verbose logging |

The CSV must be a recent `audit-scan` output so depth-1 duplicates are visible.

## Command line

```bash
# Always start with a dry-run
python -m drive_audit.commands --config data/config.yml merge_client_folders --dry-run

# Apply against an explicit CSV
python -m drive_audit.commands --config data/config.yml merge_client_folders \
  --csv-file data/files.csv
```

## Outputs

| Artefact | Description |
|----------|-------------|
| `data/merge_client_folders.log` | Per-folder move/delete log |
| `data/merge_client_folders.csv` | Plan/record of moves — used by `revert_merge_client_folders.py` |
| Google Drive | One folder per client; duplicate folders removed |

## Pitfalls

- Refresh `files.csv` (run `audit-scan`) right before merging — stale data merges into the wrong "canonical" folder.
- The choice of canonical folder is determined inside the script; verify the dry-run plan before applying.
- If the wrong folder was kept, `python revert_merge_client_folders.py` undoes the run using `data/merge_client_folders.csv`.
- Service account needs delete rights on the Shared Drive.
