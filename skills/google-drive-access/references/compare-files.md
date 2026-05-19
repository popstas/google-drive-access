# compare_files — diff two Shared Drive snapshots

## Purpose

Diff two `files.csv` snapshots by normalized `location` and write rows that exist only in the old or only in the new export. Pure local CSV work — no Drive API calls.

## When to use

- Verifying nothing was lost after a drive migration or `merge_client_folders` run.
- Tuning normalization (Google ↔ Office format mapping, duplicate suffixes, ignored folders).
- Before closing a migration milestone (then run `check_compare_results.py` and `find_similar_files.py`).

## Inputs

Positional args:

| Arg | Description |
|-----|-------------|
| `csv_old` | Baseline export (typically `data/files.csv`) |
| `csv_new` | New export (typically `data/new_files.csv`) |

Config (`data/config.yml` → `compare:`):

| Key | Effect |
|-----|--------|
| `normalize_file_names` | Replace forbidden filename chars with `_` |
| `ignore_format_differences` | Treat a Google Doc and its Office export (e.g. `.docx`) as the same item |
| `ignore_duplicate_suffixes` | Drop `(1)`, `(2)` suffixes when comparing |
| `ignore_folders` | List of folder names to exclude entirely |
| `ignore_empty_folders` | Skip empty folders |
| `ignore_public_subdir` | Ignore the `public_subdir` folder itself (children are still compared) |

## Command line

```bash
python -m drive_audit.commands --config data/config.yml compare_files \
  data/files.csv data/new_files.csv

# With debug logging
python -m drive_audit.commands --config data/config.yml --debug compare_files \
  data/files.csv data/new_files.csv
```

## Outputs

| File | Contents |
|------|----------|
| `data/compare_only_old.csv` | Rows present only in `csv_old` |
| `data/compare_only_new.csv` | Rows present only in `csv_new` |
| `data/compare_format_mismatches.csv` | Format-conversion candidates (when enabled) |
| `data/compare_files.log` | Operation log |

Note: `data/.compare_results.json` is written by `check_compare_results.py`, not by `compare_files` itself — run that script afterwards to produce/refresh it.

## Pitfalls

- Without `ignore_format_differences`, legitimate Google→Office conversion pairs appear as false-positive diffs.
- Per project convention: after any normalization change, run `compare_files` again, then `python check_compare_results.py` to confirm diff counts didn't grow.
- Filenames are compared case-sensitively unless normalization handles it — `ignore_duplicate_suffixes` is the usual fix.
