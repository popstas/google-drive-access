# check_compare_results.py — regression gate for compare

## Purpose

Record the row counts of `compare_only_new.csv` and `compare_only_old.csv` after a `compare_files` run and compare them with the previous baseline. Used as a simple regression check: normalization edits should make both counters **decrease**. Matches the "Compare Command Guidelines" workflow in `CLAUDE.md`.

## When to use

- Before starting a series of `normalize_location` edits — capture a baseline.
- After every edit → re-run `compare_files` → run this script. It updates the baseline on its own.
- As an exit-code gate inside a local wrapper script (e.g. before committing a normalization tweak).

## Hardcoded inputs

Paths are constants at the top of the script (`check_compare_results.py:12-14`). Run from the repo root.

| File | Use |
|------|-----|
| `data/compare_only_new.csv` | Row count (header excluded) |
| `data/compare_only_old.csv` | Row count (header excluded) |
| `data/.compare_results.json` | Previous counts; absent on first run (current values become the baseline) |

## Command line

```bash
# Step 1 — refresh the compare output
.venv/bin/python -m drive_audit.commands --config data/config.yml compare_files \
  data/files.csv data/new_files.csv

# Step 2 — regression check
.venv/bin/python check_compare_results.py
```

Exit code 0 = both counters decreased OR no previous baseline (first run). Exit code 1 = a previous baseline exists and at least one counter did not decrease (use as a rollback signal in a wrapper script).

## Outputs

| Artifact | Description |
|----------|-------------|
| `data/.compare_results.json` | `{"new_only": int, "old_only": int}` — overwritten on every run |
| stdout | Old vs new counts, verdict (`SUCCESS` / `PARTIAL` / `WARNING`), deltas |
| exit code | 0 — both decreased or no baseline; 1 — baseline exists and at least one counter did not decrease |

## Pitfalls

- The baseline file is **always** overwritten with the latest counts, even when the verdict is failure. Copy `.compare_results.json` aside (or commit it) if you need a hard pre-commit gate.
- The metric is row count only. It cannot tell "fixed by normalization" from "fewer inputs". For the full picture combine with `find_similar_files.py`.
- The script does not run `compare_files` itself — the caller is responsible for that.
- First run prints "No previous results found" and exits 0 — that is the baseline-capture path, not an error.
