# find_extra_author_access.py — authors with access beyond active assignments

## Purpose

Cross-reference `permissions.csv` with a Planfix snapshot of active tasks and identify direct (non-inherited) author access to client folders that is **not** justified by an active assignment. Emits two artifacts: a removal list for `remove_access` and a list of non-author direct access for manual review.

## When to use

- Periodic audit of author folders: a task closed in Planfix but the author still has direct access on the Drive folder.
- After a bulk access grant: see which non-authors ended up with direct access to client folders.
- Preparing input for the `remove_access` command.

## Hardcoded inputs

Paths live inside the script (`find_extra_author_access.py:21-26`) — run from the repo root or edit the constants. Provide these files under `data/`:

| File | Columns used | Purpose |
|------|--------------|---------|
| `data/science_emails.csv` | `email` | Set of author emails (lower-cased) |
| `data/<YYYY-MM-DD>-active_science_articles.csv` | `Google Drive клиента`, `Google аккаунт исполнителя` | `(folder_id, executor_email)` pairs derived from the article export |
| `data/permissions.csv` | `file_id`, `location`, `permission_type`, `permission_email`, `inherited`, … | Source of permission rows (produced by `audit-scan`) |

Only level-1 client folders are considered (`location` starts with `/` and contains exactly one `/`). Only rows with `inherited=False` and `permission_type=user` flow through.

## Command line

```bash
# From the repo root (paths are relative to CWD)
.venv/bin/python find_extra_author_access.py
```

No CLI arguments. To point at a different active-articles snapshot, edit `ACTIVE_ARTICLES` at the top of the script.

## Outputs

| File | Contents |
|------|----------|
| `data/remove-access.csv` | Author rows whose `(file_id, email)` pair is not in active assignments — feeds `remove_access` |
| `data/non-author-client-access.csv` | Direct access from emails **not** in the authors list (needs manual triage) |
| stdout | Counts of folders scanned, direct rows, skipped non-user rows, and a Counter by email |

## Pitfalls

- The script never deletes anything — it only prepares CSVs. Apply removals via `remove_access` with `--dry-run` first.
- The active-tasks CSV is a snapshot. A stale Planfix export will mark current assignments as "extra".
- Inherited rows are intentionally skipped — they vanish once the originating root permission is removed.
- Date in the filename (`2026-05-18-active_science_articles.csv`) changes per export; update `ACTIVE_ARTICLES` accordingly.
