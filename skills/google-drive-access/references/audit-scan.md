# audit-scan — full Shared Drive audit

## Purpose

Scan a Google Shared Drive end-to-end: walk the file/folder tree, collect permissions, run policy checks (public files outside `public_subdir`), and export the result to YAML + flat CSVs that downstream commands consume.

## When to use

- Regular security/structure audit of a Shared Drive.
- Producing `files.csv` / `permissions.csv` before running `compare_files`, `remove_access`, `merge_client_folders`, `delete_empty_folders`.
- First inventory after the service account is added to a new drive.

## Inputs

Config (`data/config.yml`):

| Key | Purpose |
|-----|---------|
| `drive.id` | Shared Drive ID |
| `drive.root_folder_id` | Root subfolder ID, or `ROOT_FOLDER_ID` sentinel to use the drive root |
| `scan.include_trashed` | Include trashed items |
| `scan.collect_permissions` | Toggle permission collection (`false` is much faster) |
| `scan.collect_permissions_max_level` | Cap depth of permission collection (`1` = client folders only) |
| `scan.max_depth` | Cap depth of tree walk |
| `scan.public_subdir` | Name of the "public" subfolder used by the policy check |
| `output.dir`, `output.yaml_file`, `output.files_csv`, `output.permissions_csv` | Output paths |

CLI flags:

- `--config <path>` (default `data/config.yml`)
- `--drive-id <DRIVE_ID>` — override `drive.id`
- `--root-folder-id <FOLDER_ID>` — override `drive.root_folder_id`
- `--debug` — DEBUG-level logging

## Command line

```bash
# Standard run from data/config.yml
python -m src.drive_audit.main --config data/config.yml

# Override target drive/root for a one-off scan
python -m src.drive_audit.main --config data/config.yml \
  --drive-id <DRIVE_ID> --root-folder-id <ROOT_FOLDER_ID>

# Verbose
python -m src.drive_audit.main --config data/config.yml --debug
```

## Outputs

| File | Contents |
|------|----------|
| `data/drive_audit.yml` | Hierarchical tree with metadata and policy flags |
| `data/files.csv` | Flat file list with `location`, `file_id`, policy flags |
| `data/permissions.csv` | Flat permissions list (empty if `collect_permissions: false`) |
| `data/app.log` | Loguru log (10 MB rotation, 30-day retention) |

## Pitfalls

- Full permission collection on a large drive is slow and burns API quota — use `scan.collect_permissions_max_level: 1` for big drives.
- Never commit `data/service-account.json` or a populated `config.yml` to git.
- The policy check depends on `scan.public_subdir` matching the actual folder name on the drive.
