# filter_permissions — local subset of permissions.csv by email

## Purpose

Filter `permissions.csv` rows where `permission_email` matches any of the supplied emails and write the matching rows to a new CSV. Pure local processing — no Google API calls, no Drive auth.

## When to use

- Producing a per-user access report (e.g. "all access of `user@example.com`").
- Building the `remove-access.csv` input for `remove_access` from a full audit.
- HR/security reports listing a handful of accounts.

## Inputs

CLI flags:

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--emails <a,b,c>` | yes | — | Comma-separated emails (exact match) |
| `--csv-save <path>` | yes | — | Output CSV path |
| `--csv-file <path>` | no | `data/permissions.csv` | Input CSV |
| `--config <path>` | no | `data/config.yml` | Config (read but Drive/auth NOT required) |
| `--debug` | no | — | Verbose logging |

Drive config and the service account are not used by this command (`filter_permissions` is in `NO_DRIVE_CONFIG_COMMANDS` / `NO_SERVICE_COMMANDS`).

## Command line

```bash
# Default input (data/permissions.csv)
python -m drive_audit.commands --config data/config.yml filter_permissions \
  --emails user1@example.com,user2@example.com \
  --csv-save data/filtered.csv

# Explicit input
python -m drive_audit.commands --config data/config.yml filter_permissions \
  --emails user1@example.com \
  --csv-file data/permissions.csv \
  --csv-save data/filtered.csv
```

## Outputs

| File | Description |
|------|-------------|
| Path passed to `--csv-save` | Matching rows (all original columns preserved) |
| `data/filter_permissions.log` | Operation log |

## Pitfalls

- Exact match only — case-insensitive (both sides lowercased) and no wildcards. Typos in `--emails` silently produce an empty CSV.
- This command does not mutate Drive; pair it with `remove_access` if you want the matching rows actually revoked.
