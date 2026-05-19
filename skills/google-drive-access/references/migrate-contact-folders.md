# migrate_contact_folders — repoint Planfix contact folders to a new Drive

## Purpose

After moving the Shared Drive (e.g. to a new corporate drive), update Planfix contact records so each contact's "Google Drive folder" URL points at the new drive. Reads the old/new drive mapping locally; optionally writes back to Planfix.

## When to use

- Cutover to a new Shared Drive when contacts in Planfix reference the old drive's folders.
- Bulk-fixing stale folder URLs in CRM after structural changes.

## Inputs

Input CSV (`data/contacts-with-old-folder.csv` by default — path is hardcoded in `migrate_contact_folders()`):

| Column | Description |
|--------|-------------|
| `Дополнительная информация` | Free-text field containing an old-drive folder URL (used to extract the old folder ID) |
| `Ссылка на Google Drive папку клиента` | Populated by the script with the new folder URL or an `error: ...` message; rows already populated are skipped |

The CSV is **rewritten in place** on every run regardless of `--write-to-contacts` — back it up first.

Config (`data/config.yml`):

- The active config points at the **new** drive. Old-drive folder IDs come from the input CSV's `Дополнительная информация` column and are looked up through the same service-account credentials, so the service account needs read access to both drives.
- Planfix endpoints under `planfix.*` are only required when running with `--write-to-contacts`; without that flag, Planfix is not contacted at all:

```yaml
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
```

CLI flags:

- `--write-to-contacts` — actually update Planfix contacts (calls `planfix.update_contact` to PUT/POST the new folder URL). Without it, Planfix is **not** contacted at all; the script only resolves folder IDs against Google Drive and rewrites the local CSV.

Global flags `--config` / `--debug` go before the subcommand (see SKILL.md Quick Reference).

## Command line

```bash
# Preview: no Planfix calls at all; resolves folder IDs via Drive and rewrites the local CSV
python -m drive_audit.commands --config data/config.yml migrate_contact_folders

# Apply: writes the new folder URL into each contact in Planfix
python -m drive_audit.commands --config data/config.yml migrate_contact_folders \
  --write-to-contacts
```

## Outputs

| Artefact | Description |
|----------|-------------|
| `data/migrate_contact_folders.log` | Per-contact log with old → new folder mapping and any errors |
| Planfix (when `--write-to-contacts`) | Contact "Google Drive folder" field updated to the new drive's URL |

## Pitfalls

- The input CSV is rewritten in place every run — even without `--write-to-contacts`. "Preview" means "no Planfix writes"; local CSV is still mutated. Back up the CSV before each run.
- Always do a preview run first and skim the log for duplicate name matches.
- Duplicate folder names on the new drive cause ambiguous matches — resolve with `merge_client_folders` first.
- Planfix API errors for individual contacts are caught and logged; the batch continues. Re-run after fixing the underlying contact data.
- Planfix tokens belong in `config.yml` only; never commit them.
