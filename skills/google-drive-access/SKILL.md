---
name: google-drive-access
description: Navigation hub for the google-drive-access project. Use when auditing Google Shared Drives, scanning files and permissions, comparing scans, moving files into public folders, migrating Planfix contact folders, merging client folders, removing access, or running standalone debug scripts. Triggers on "google drive audit", "shared drive scan", "drive permissions", "planfix folder", "compare drive files", "client folder", "audit-scan", "move_files_to_public_folder", "merge_client_folders", "find_similar_files".
---

# google-drive-access

Skill for the google-drive-access CLI/HTTP project: maps a task to the right command or standalone script, with anonymized inputs and a pointer to the detailed runbook.

## When to Use

Use this skill when the user is working inside the google-drive-access repository and asks about:

- auditing a Google Shared Drive (file tree, permissions, policy violations)
- moving files into a public subfolder (by regex or via CSV manifest)
- comparing two scans (`files.csv` vs `new_files.csv`) and rechecking diffs
- migrating Planfix contact folders, merging duplicate client folders, deleting empty folders
- moderated deletion: synchronizing items whose names contain `+delete` into a Sheet and trashing human-approved ones (`moderate_delete`)
- listing drive link metadata, removing access by user, filtering permissions CSVs
- one-off standalone scripts in the repo root (`find_*.py`, `check_compare_results.py`, `revert_merge_client_folders.py`)

HTTP endpoints are out of scope for this skill — see `README.md` and `data/use-cases/http-*.md` for those.

## Quick Reference

All 17 single-command scenarios plus 1 composite workflow. CLI commands run as `python -m drive_audit.commands --config data/config.yml <command>` unless noted. Standalone scripts run as `python <script>.py` from the repo root.

Note: `--config` and `--debug` are top-level flags of `python -m drive_audit.commands` — they must appear **before** the subcommand name (e.g. `python -m drive_audit.commands --config data/config.yml --debug merge_client_folders ...`). Subcommand-specific flags (`--csv-file`, `--dry-run`, `--emails`, etc.) appear after the subcommand.

| # | Scenario | Command / script | Reference | Typical inputs |
|---|----------|------------------|-----------|----------------|
| 1 | Full Shared Drive audit (file tree, permissions, policy) | `python -m src.drive_audit.main` | [audit-scan.md](references/audit-scan.md) | `data/config.yml`, service account JSON |
| 2 | Move files into the public subfolder by regex | `move_files_to_public_folder` | [move-files-to-public-folder.md](references/move-files-to-public-folder.md) | `commands.move_files_to_public_folder.file_match` / `mimeType_match` in config |
| 3 | Move files into target folders via CSV manifest | `move_files_csv` | [move-files-csv.md](references/move-files-csv.md) | `data/move_files.csv` |
| 4 | Compare two scans (`files.csv` vs `new_files.csv`) | `compare_files <csv_old> <csv_new>` | [compare-files.md](references/compare-files.md) | two CSV paths (positional args: `csv_old`, `csv_new`), `compare.*` config |
| 5 | Recheck a list of files against current Drive state | `recheck_files` | [recheck-files.md](references/recheck-files.md) | CSV with a `file_id` column (or `--file-ids` directly) |
| 6 | Migrate Planfix contact folders into the drive | `migrate_contact_folders` | [migrate-contact-folders.md](references/migrate-contact-folders.md) | contacts CSV, Planfix endpoints in config |
| 7 | Merge duplicate client folders (level-1) | `merge_client_folders` | [merge-client-folders.md](references/merge-client-folders.md) | `--csv-file` (default `data/new_disk/new_files.csv`) |
| 8 | Delete empty folders | `delete_empty_folders` | [delete-empty-folders.md](references/delete-empty-folders.md) | `data/files.csv` |
| 9 | Resolve drive links to metadata (id, name, path) | `drive_links_info` | [drive-links-info.md](references/drive-links-info.md) | CSV with folder/file URLs |
| 10 | Remove access entries for users / domains | `remove_access` | [remove-access.md](references/remove-access.md) | `data/remove-access.csv` |
| 11 | Filter a permissions CSV by exact email (case-insensitive, no wildcards) | `filter_permissions` | [filter-permissions.md](references/filter-permissions.md) | required `--emails user1@example.com,user2@example.com` and `--csv-save <out>`; `--csv-file` defaults to `data/permissions.csv` |
| 11a | Moderated deletion: synchronize names containing `+delete`, trash human-approved items | `moderate_delete scan\|watch\|apply\|report` | [moderate-delete.md](references/moderate-delete.md) | `scan_roots` limits traversal; `watch` uses `scan_interval_seconds`; removing the marker removes the item from the actionable queue; apply revalidates marker/scope/trash state; Activity + People record and optionally restrict the renamer |
| 12 | Find authors with extra access beyond their articles | `python find_extra_author_access.py` | [find-extra-author-access.md](references/find-extra-author-access.md) | `science_emails.csv`, `<YYYY-MM-DD>-active_science_articles.csv` (filename hardcoded in script), `permissions.csv` |
| 13 | Find authors still on inactive folders | `python find_authors_on_inactive_folders.py` | [find-authors-on-inactive-folders.md](references/find-authors-on-inactive-folders.md) | same three CSVs as #12 |
| 14 | Find similar file pairs between two scans | `python find_similar_files.py` | [find-similar-files.md](references/find-similar-files.md) | `compare_only_old.csv`, `compare_only_new.csv` |
| 15 | Sanity-check a compare run (counts, diffs) | `python check_compare_results.py` | [check-compare-results.md](references/check-compare-results.md) | `compare_only_*.csv`, `.compare_results.json` |
| 16 | Revert a `merge_client_folders` run | `python revert_merge_client_folders.py` | [revert-merge-client-folders.md](references/revert-merge-client-folders.md) | `data/merge_client_folders.csv` |
| 17 | Revoke all direct access of a single user (offboarding) — composite | `filter_permissions` + `remove_access` | [remove-user-access.md](references/remove-user-access.md) | email(s) to revoke, fresh `data/permissions.csv` |

## Setup

Prerequisites:

- Python 3.11+
- Install dependencies: `pip install .` (or `pip install .[test]` for the test extras)
- Google service account JSON at `data/service-account.json`
- Service account added to the target Shared Drive with sufficient roles (typically `organizer` or `content manager` for write operations; `viewer` is enough for read-only audits)
- Project config at `data/config.yml` (copy from `data/config.example.yml` and fill in real values)

Anonymized config snippet (full reference in `data/config.example.yml` and project README):

```yaml
lang: "en"
logLevel: "INFO"

google:
  credentials_file: "data/service-account.json"
  # delegated_user: "admin@example.com"

drive:
  id: "<DRIVE_ID>"
  root_folder_id: "<ROOT_FOLDER_ID>"   # or "ROOT_FOLDER_ID" sentinel to default to drive.id
  root_folder_name: "Clients"
  writer_subdir: ""

scan:
  include_trashed: false
  include_shortcuts: true
  collect_permissions: true
  collect_permissions_max_level: null   # null = all depths; 1 = client folders only
  max_depth: null
  public_subdir: "public"

compare:
  ignore_public_subdir: false
  normalize_file_names: false
  ignore_format_differences: false
  ignore_duplicate_suffixes: false
  ignore_empty_folders: false
  ignore_folders: []

commands:
  move_files_to_public_folder:
    file_match:
      - ".*?KP.*?"
    mimeType_match:
      - "application/vnd.google-apps.spreadsheet"
  move_files_csv:
    csv_file: "data/move_files.csv"

output:
  dir: "./data"
  yaml_file: "drive_audit.yml"
  files_csv: "files.csv"
  permissions_csv: "permissions.csv"

planfix:
  getChildTasks:
    url: "https://planfix.example.com/tasks"
    token: "<TOKEN>"
  getManager:
    url: "https://planfix.example.com/manager"
    token: "<TOKEN>"
  getClientTask:
    url: "https://planfix.example.com/client-task"
    token: "<TOKEN>"
  updateContact:
    url: "https://planfix.example.com/update-contact"
    token: "<TOKEN>"
  role: "writer"
  timeout: 120

share_file:
  days: 90
  role: commenter

http:
  port: 7587
  token: "<TOKEN>"
```

Notes:
- Replace every `<DRIVE_ID>`, `<ROOT_FOLDER_ID>`, `<TOKEN>` with real values before running.
- For most read-only audits a `viewer` role on the Shared Drive is enough; mutating commands (move / merge / delete / remove_access) require write permissions.
- Most commands write to `output.dir` (default `./data`). Back up `data/files.csv` and `data/permissions.csv` before running mutating commands.

## Common Workflows

Recipe 1 — Audit a drive, then move public files into the public subfolder

1. Run `python -m src.drive_audit.main --config data/config.yml` to produce `data/files.csv`, `data/permissions.csv`, and `data/drive_audit.yml`. See [audit-scan.md](references/audit-scan.md).
2. Inspect the policy report inside `drive_audit.yml` for public files outside `public_subdir`.
3. Adjust `commands.move_files_to_public_folder.file_match` / `mimeType_match` in config to target the right files.
4. Run `python -m drive_audit.commands --config data/config.yml move_files_to_public_folder`. See [move-files-to-public-folder.md](references/move-files-to-public-folder.md).
5. Re-run the audit (step 1) to confirm the violations disappeared.

Recipe 2 — Compare two scans and recheck the differences

1. Run `audit-scan` once to produce `data/files.csv` (the "old" snapshot).
2. Later, run `audit-scan` again and rename the output to `data/new_files.csv`.
3. Run `python -m drive_audit.commands --config data/config.yml compare_files data/files.csv data/new_files.csv` (both CSV paths are required positional args). Outputs `compare_only_old.csv` and `compare_only_new.csv` (`.compare_results.json` is produced in the next step by `check_compare_results.py`). See [compare-files.md](references/compare-files.md).
4. Run `python check_compare_results.py` to summarize the diff and catch normalization issues. See [check-compare-results.md](references/check-compare-results.md).
5. Run `python find_similar_files.py` to surface near-duplicates between the two scans. See [find-similar-files.md](references/find-similar-files.md).
6. If diffs are real, feed them to `recheck_files` to confirm current Drive state. See [recheck-files.md](references/recheck-files.md).

Recipe 3 — Clean up a drive: merge duplicate client folders, then delete empty folders

1. Run `audit-scan` to refresh `data/files.csv`.
2. Run `python -m drive_audit.commands --config data/config.yml merge_client_folders`. Review the generated `data/merge_client_folders.csv` plan before letting it apply. See [merge-client-folders.md](references/merge-client-folders.md).
3. If the merge was wrong, run `python revert_merge_client_folders.py` to undo. See [revert-merge-client-folders.md](references/revert-merge-client-folders.md).
4. Run `python -m drive_audit.commands --config data/config.yml delete_empty_folders` to prune. See [delete-empty-folders.md](references/delete-empty-folders.md).
5. Re-run `audit-scan` to confirm the new state.

Recipe 4 — Find and remove stale author access on inactive folders

1. Prepare `science_emails.csv` (authors of interest), `<YYYY-MM-DD>-active_science_articles.csv` (active folders — the date prefix is hardcoded in the scripts, edit `ACTIVE_ARTICLES` to match), and a fresh `permissions.csv` from `audit-scan`.
2. Run `python find_authors_on_inactive_folders.py` — writes `data/remove-access-inactive-folders.csv`. See [find-authors-on-inactive-folders.md](references/find-authors-on-inactive-folders.md).
3. Optionally cross-check with `python find_extra_author_access.py`. See [find-extra-author-access.md](references/find-extra-author-access.md).
4. Dry-run, then apply: `python -m drive_audit.commands --config data/config.yml remove_access --csv-file data/remove-access-inactive-folders.csv --dry-run`, review, then re-run without `--dry-run`. See [remove-access.md](references/remove-access.md).

Recipe 5 — Revoke all direct access of a single user (offboarding)

1. Refresh `data/permissions.csv` via `audit-scan`.
2. Slice the snapshot for the email with `filter_permissions --emails user@example.com --csv-save data/remove-access-<slug>.csv`.
3. Dry-run `remove_access --csv-file data/remove-access-<slug>.csv --dry-run` and review the root/inherited split.
4. Apply with `remove_access --csv-file data/remove-access-<slug>.csv`.
5. Re-run `audit-scan` and confirm the email no longer appears in `permissions.csv`.

See [remove-user-access.md](references/remove-user-access.md) for the full runbook.

## Reference Files

Per-command runbooks live in `references/` — one file per CLI command and one per standalone script. Follow the link in the Quick Reference table to jump to a specific runbook.
