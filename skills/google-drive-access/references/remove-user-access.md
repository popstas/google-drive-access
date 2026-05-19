# remove-user-access — revoke all direct access of a single user

## Purpose

Fully remove one (or a small group of) `email`s from a Shared Drive by combining `filter_permissions` (slice the snapshot) and `remove_access` (delete the root permissions). Used for offboarding employees, ending contractor engagements, or revoking access after a security incident.

## When to use

- An employee left and still appears in `data/permissions.csv`.
- An external contributor's engagement ended.
- A security review identified accounts to remove from the drive.

## Inputs

- Fresh `data/permissions.csv` from `python -m src.drive_audit.main --config data/config.yml` (see [audit-scan.md](audit-scan.md)).
- The email address(es) to revoke. Comma-separate to revoke several at once.
- Service account with `permissions.delete` on the drive (manager-equivalent role).

## Pipeline

### 1. Filter the snapshot for the user's rows

```bash
python -m drive_audit.commands --config data/config.yml filter_permissions \
  --emails user@example.com \
  --csv-file data/permissions.csv \
  --csv-save data/remove-access-<slug>.csv
```

`--emails` accepts a comma-separated list to revoke a batch in one go. Match is exact, case-insensitive. See [filter-permissions.md](filter-permissions.md).

### 2. Dry-run the revoke and review the report

```bash
python -m drive_audit.commands --config data/config.yml remove_access \
  --csv-file data/remove-access-<slug>.csv \
  --dry-run
```

The dry-run log groups rows into `root permissions (will be deleted)` and `inherited permissions (will be skipped)`. Only root permissions are deleted — inherited entries disappear automatically once the parent grant is revoked. See [remove-access.md](remove-access.md).

### 3. Apply the revoke

```bash
python -m drive_audit.commands --config data/config.yml remove_access \
  --csv-file data/remove-access-<slug>.csv
```

Log: `data/remove_access.log`. The summary should show `Successfully deleted: N permission(s)` and no `Failed:` entries.

### 4. Re-scan to confirm

```bash
python -m src.drive_audit.main --config data/config.yml
```

After the re-scan, `grep -c user@example.com data/permissions.csv` should return `0`.

## Outputs

| Artefact | Description |
|----------|-------------|
| `data/remove-access-<slug>.csv` | Filtered snapshot of the user's permission rows |
| `data/remove_access.log` | Per-file delete attempts and totals |
| Updated `data/permissions.csv` (after step 4) | Refreshed snapshot without the revoked email |

## Pitfalls

- Drive revocations via this command are **irreversible** — restoring access means re-granting it manually. Always do step 2 (dry-run) first.
- Never hand-edit `data/permissions.csv`; it is a snapshot of Drive state and is overwritten by the next audit-scan.
- `remove_access` matches on `permission_id`. If the filtered CSV was round-tripped through Excel, IDs may end up in scientific notation — `_fix_scientific_notation` in `src/drive_audit/commands/remove_access.py` corrects this automatically.
- `inherited` rows are silently skipped by `remove_access`. If the user retains access after revoke, look for a parent folder still granting access and add that folder's grant to the removal list.
