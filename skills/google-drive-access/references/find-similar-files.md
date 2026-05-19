# find_similar_files.py — diagnose leftover compare diffs

## Purpose

After `compare_files` runs, look at why rows remain in `compare_only_old.csv` / `compare_only_new.csv`: pairwise-compare `location` columns with `difflib.SequenceMatcher` and group near-matches by failure pattern (URL-encoding, path-depth change, missing extension).

## When to use

- Iteratively tuning `normalize_location` (see "Compare Command Guidelines" in `CLAUDE.md`).
- Discovering "same file, two paths" pairs that the current compare treats as different.
- Inspecting which patterns need to be added to normalization before another `compare_files` pass.

## Hardcoded inputs

Paths and the similarity threshold live in the script's `__main__` block (`find_similar_files.py:109-115`). Run from the repo root or edit those lines.

| File | Columns used | Purpose |
|------|--------------|---------|
| `data/compare_only_old.csv` | `location`, `file_id`, `name`, `mimeType` | Old-only rows from `compare_files` |
| `data/compare_only_new.csv` | same | New-only rows from `compare_files` |

Threshold default: `0.95`.

## Command line

```bash
.venv/bin/python find_similar_files.py
```

No CLI arguments. Change inputs/threshold by editing `__main__`.

## Outputs

| File | Contents |
|------|----------|
| `data/similar.csv` | Pairs with similarity ≥ threshold, sorted descending; columns `similarity`, `old_location`, `old_file_id`, `old_name`, `old_mime_type`, `new_location`, `new_file_id`, `new_name`, `new_mime_type` |
| stdout | Total pair count + grouped examples by pattern: `url_encoded` (`%2F`/`_2F`), `path_structure` (segment count differs), `missing_extension` |

## Pitfalls

- Cost is O(n_old × n_new) — full dumps with tens of thousands of rows take hours. Only run on freshly-filtered `compare_only_*.csv` with at most a few thousand rows.
- The `0.95` threshold is empirical; dropping to `0.85` produces a lot of noise.
- Read-only — produces a CSV for human review; does not change Drive or rewrite `compare_only_*.csv`.
- Input encoding is `utf-8-sig` (Excel BOM-aware).
