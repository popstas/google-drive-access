# close_public_client_folders.py — replace a client folder's public link with named access

## Purpose

Take client folders that are open to `anyone with the link`, give the client a named permission on their own email first, and only then delete the `anyone` permission. One folder at a time, with a per-folder audit row.

The order is the whole point. For most clients the public link is the only way into their folder — revoking it first locks them out of their own materials.

## When to use

- After an audit found client folders with an `anyone` permission (`policy_is_public_anyone == True` in `files.csv`).
- Wave-style cleanup: the gmail subset first (a gmail address is already a Google account, so the named grant just works), other mail domains later, once someone has talked to the client.

## Inputs

CLI flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--csv <path>` | `data/public-drive-folders-contacts.csv` | Mapping CSV. Required columns: `folder_id`, `contact_email`. Optional, used for the log only: `drive_client_name`, `contact_id`. Produced by `map-public-drive-folders.ts` in the planfix-api-client repo |
| `--apply` | off | Actually grant and revoke. Without it the run is a preview and touches nothing |
| `--all-emails` | off | Process every row with an email. By default only `@gmail.com` rows are taken |
| `--role <role>` | `commenter` | Role for the client's named permission |
| `--limit <n>` | `0` (all) | Process at most N folders — use it for the first batch |
| `--pause <sec>` | `0.2` | Sleep between folders |
| `--log <path>` | `data/close-public-client-folders.csv` | Audit log path |
| `--config <path>` | `data/config.yml` | Config with the service account and `drive_id` |
| `--debug` | off | DEBUG-level logging |

Service account needs permission management on the Shared Drive (`organizer` / content manager).

## Command line

```bash
# Preview the whole gmail wave — no writes
.venv/bin/python close_public_client_folders.py

# First batch of three, verify by hand afterwards
.venv/bin/python close_public_client_folders.py --apply --limit 3 --log data/close-wave1-batch1.csv

# The rest (already-closed folders are skipped on re-run)
.venv/bin/python close_public_client_folders.py --apply --log data/close-wave1.csv
```

## Outputs

| Artifact | Description |
|----------|-------------|
| `--log` CSV | One row per folder: `folder_id, client_name, contact_id, email, grant, revoke, status, details` |
| `data/close_public_client_folders.log` | Full loguru log |
| Google Drive | Client email added as `commenter`; `anyone` permission deleted |

Statuses: `preview`, `closed`, `already_closed`, `grant_failed`, `revoke_failed`.

## Behavior notes

- Current permissions are read from the API per folder, so the run is idempotent: a folder with no `anyone` permission is reported `already_closed` and skipped. Re-running after a partial run is safe.
- A folder is never closed when the grant failed — the row is logged `grant_failed` and the public link stays.
- `add_user_permission` sends no notification email (`sendNotificationEmail=False`), so clients are not told anything by Google. Telling them is a separate, human decision.
- If the client already has a named permission on that email, the grant step is skipped and the row is logged `grant=existing`.
- The audit log is flushed after every row, so an interrupted run still leaves a usable trail.

## Pitfalls

- **Never widen `--all-emails` without checking the domains first.** A named Drive permission only works on a Google account. Handing `commenter` to `client@mail.ru` silently grants nothing, and then the link removal locks the client out.
- Drive cannot time-box this: `expirationTime` is accepted on `user` and `group` permissions only, and on folders only for the `reader` role. There is no "public link that expires" and no "temporary commenter on a folder".
- The mapping CSV can go stale — folders get created and closed between runs. Re-generate it rather than reusing an old one for a new wave.
- Rows with an empty `contact_email` are skipped at read time and never appear in the log. Count the input rows if you need to know how many were dropped.
