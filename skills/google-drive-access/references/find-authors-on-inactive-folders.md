# find_authors_on_inactive_folders.py — authors on folders with no active task at all

## Purpose

A stricter subset of `find_extra_author_access.py`: emit only author rows on client folders that do **not appear** in the active-tasks snapshot at all (versus folders that exist but were reassigned). Safe-by-default candidate list for the first wave of `remove_access`.

## When to use

- Cleanup after a long quiet period: some clients are gone from Planfix but their Drive folders still carry author access.
- Low-risk first batch before tackling the broader output of `find_extra_author_access.py`.

## Hardcoded inputs

Paths are defined at the top of the script (`find_authors_on_inactive_folders.py:19-23`). Run from the repo root or edit the constants. Provide under `data/`:

| File | Columns used | Purpose |
|------|--------------|---------|
| `data/science_emails.csv` | `email` | Author email set |
| `data/<YYYY-MM-DD>-active_science_articles.csv` | `Google Drive клиента` | Active folder IDs |
| `data/permissions.csv` | level-1 client folder rows | Source of permission rows |

Only `inherited=False`, `permission_type=user`, and `email ∈ science_emails.csv` rows are kept; folders whose `file_id` appears in the active set are dropped first.

## Command line

```bash
.venv/bin/python find_authors_on_inactive_folders.py
```

No CLI arguments. To target a different active-articles snapshot, edit `ACTIVE_ARTICLES`.

## Outputs

| File | Contents |
|------|----------|
| `data/remove-access-inactive-folders.csv` | Author direct-access rows on fully-inactive folders, in `permissions.csv` schema |
| stdout | Inactive folders scanned, distinct folders with author access, Counter by author email |

## Pitfalls

- Read-only — does not call Drive API.
- "Inactive" means absent from the active-tasks CSV. A stale Planfix export will sweep current clients into the removal list.
- Only `science_emails.csv` authors are reported. Non-author direct access is invisible here; use `find_extra_author_access.py` for that.
- Inherited permissions are intentionally skipped (they cannot be removed via the API and will disappear with the parent rule).
