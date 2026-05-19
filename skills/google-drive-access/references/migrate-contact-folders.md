# migrate_contact_folders — repoint Planfix contact folders to a new Drive

## Purpose

After moving the Shared Drive (e.g. to a new corporate drive), update Planfix contact records so each contact's "Google Drive folder" URL points at the new drive. Reads the old/new drive mapping locally; optionally writes back to Planfix.

## When to use

- Cutover to a new Shared Drive when contacts in Planfix reference the old drive's folders.
- Bulk-fixing stale folder URLs in CRM after structural changes.

## Inputs

Config (`data/config.yml`):

- The active config points at the **new** drive. The old drive's config is usually `data/config_old_folder.yml` and is referenced from the active one.
- Planfix endpoints under `planfix.*` are required when running with `--write-to-contacts`:

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
  role: "writer"
  timeout: 120
```

CLI flags:

- `--config <path>`
- `--write-to-contacts` — actually update Planfix; without it the run is dry / read-only on Planfix
- `--debug`

## Command line

```bash
# Preview — never writes to Planfix
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

- Always do a preview run first and skim the log for duplicate name matches.
- Duplicate folder names on the new drive cause ambiguous matches — resolve with `merge_client_folders` first.
- Planfix API errors for individual contacts are caught and logged; the batch continues. Re-run after fixing the underlying contact data.
- Planfix tokens belong in `config.yml` only; never commit them.
