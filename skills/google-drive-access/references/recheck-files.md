# recheck_files — re-fetch current Drive metadata for a list of files

## Purpose

Re-query Google Drive for the latest metadata of a specific set of files (by `file_id` or `location`), without running a full drive audit. Produces a small results CSV instead of refreshing `files.csv`.

## When to use

- Validating rows from `compare_only_new.csv` / `compare_only_old.csv` after `compare_files`.
- Spot-checking that recent `move_*` / `remove_access` operations actually applied.
- Pulling current metadata for a short list before producing a report.

## Inputs

CLI flags:

| Flag | Description |
|------|-------------|
| `--csv-file <path>` | CSV with a `file_id` column (preferred) or `location` column |
| `--file-ids <ID> <ID> ...` | Space-separated list of file IDs (alternative to `--csv-file`) |
| `--output <path>` | Results CSV path (default `data/recheck_results.csv`) |
| `--config <path>` | Config (Drive auth) |
| `--debug` | Verbose logging |

At least one of `--csv-file` or `--file-ids` is required.

## Command line

```bash
# From a CSV (e.g. compare_only_new.csv)
python -m drive_audit.commands --config data/config.yml recheck_files \
  --csv-file data/compare_only_new.csv

# Ad-hoc by ID
python -m drive_audit.commands --config data/config.yml recheck_files \
  --file-ids <FILE_ID_1> <FILE_ID_2>

# Custom output
python -m drive_audit.commands --config data/config.yml recheck_files \
  --csv-file data/recheck_input.csv \
  --output data/recheck_results.csv
```

## Outputs

| File | Description |
|------|-------------|
| `data/recheck_results.csv` (or `--output`) | One row per checked file with current presence, name, mime, parents, etc. |
| `data/recheck_files.log` | Operation log |

## Pitfalls

- Large input lists can hit Drive API rate limits — split the input or rerun on the error subset.
- An invalid or revoked-access `file_id` is logged as an error row and the rest continue.
- This command requires service-account access; pure-local filtering of an existing CSV belongs in `filter_permissions` instead.
