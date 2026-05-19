# remove_access — bulk-delete root permissions listed in a CSV

## Purpose

Remove **root** (non-inherited) permissions from files according to a CSV. Used to revoke direct user/domain access that lingers after a switch to folder-level sharing.

## When to use

- Mass-revoke after `audit-scan` + `filter_permissions` produced a removal list.
- Cleaning up legacy direct shares on an older drive.
- Implementing security policy changes (e.g. revoke an ex-employee's direct access).

## Inputs

CSV (default `data/remove-access.csv`, same shape as `permissions.csv`):

| Column | Use |
|--------|-----|
| `file_id` | Drive file ID |
| `permission_id` | Permission to delete |
| `permission_email` | Used for grouped stats in the dry-run report |
| `inherited` | Must be `False` (rows where `True` are skipped) |
| `inherited_from_id` | Must be empty (inherited rows are skipped) |

CLI flags:

- `--csv-file <path>` — default `data/remove-access.csv`
- `--dry-run` — produces an aggregated report by `permission_email` without deleting
- `--config <path>`
- `--debug`

## Command line

```bash
# Preview, with per-email totals in the log
python -m drive_audit.commands --config data/config.yml remove_access --dry-run

# Apply
python -m drive_audit.commands --config data/config.yml remove_access \
  --csv-file data/remove-access.csv
```

## Outputs

| Artefact | Description |
|----------|-------------|
| `data/remove_access.log` | Per-file delete attempts, totals per email, errors |
| Google Drive | Specified direct permissions removed |

## Pitfalls

- Inherited permissions cannot be removed via the API — the script filters them out automatically; trying to force their removal will not work.
- Always `--dry-run` first and sanity-check the per-email counts in the log.
- Service account needs `permissions.delete` (i.e. manager-equivalent role).
- Individual permission errors are caught and logged; the batch continues.
