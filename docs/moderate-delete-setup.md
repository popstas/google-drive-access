# Moderated deletion setup

This guide configures filename-based moderated deletion for a human operator
working with an automation agent. It uses placeholders only. Never paste
credential contents, OAuth codes, refresh tokens, or private Drive links into
an issue, pull request, chat, or committed configuration.

## What the feature does

1. A Drive user adds `+delete` to a file or folder name.
2. `moderate_delete scan` finds marked items inside configured folder trees.
3. The application synchronizes candidates to a Google Sheet.
4. A human reviews the row and selects `yes` or `no` in `approve`.
5. `moderate_delete apply` previews the current eligible set.
6. Only `moderate_delete apply --apply` moves validated items to Drive trash.

Removing the marker cancels the request on the next successful scan and clears
the previous approval.

## Responsibilities

### Human operator

- chooses the Drive folders that are allowed to be scanned;
- owns the Google Sheet and grants only the access that is needed;
- decides whether folders may be trashed;
- reviews and approves individual rows;
- explicitly authorizes every live `apply --apply` run;
- keeps credentials outside version control.

### Automation agent

- verifies paths, IDs, configuration, scopes, and API availability;
- starts with dry-run commands;
- summarizes candidates and rejected rows;
- checks that marker removal clears approvals;
- never writes approval values unless the human explicitly requests it;
- never runs `apply --apply` without explicit human authorization;
- reports partial scans, API errors, and audit failures instead of bypassing
  them.

## Prerequisites

- Python supported by the repository;
- access to the target Google Drive or Shared Drive;
- a Google Cloud project with the required APIs;
- a Google Sheet dedicated to this queue;
- either service-account credentials or authorized-user OAuth credentials.

Install the project and test dependencies:

```bash
python -m venv .venv

# Linux/macOS
. .venv/bin/activate

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

## 1. Choose an authentication model

### Option A: service account

Use this for unattended automation and Shared Drive deployments.

1. Create a service account in a dedicated Google Cloud project.
2. Download its JSON key to a local ignored path such as
   `data/service-account.json`.
3. Grant the service account access only to the required Drive/Shared Drive and
   queue Sheet.
4. For Shared Drive trash operations, grant an appropriate role such as
   Content manager.
5. If rename attribution is required across a Workspace domain, configure
   domain-wide delegation and set `google.delegated_user`.

Required scopes by service:

- Drive: `https://www.googleapis.com/auth/drive`
- Sheets: `https://www.googleapis.com/auth/spreadsheets`
- Drive Activity:
  `https://www.googleapis.com/auth/drive.activity.readonly`
- People for delegated service accounts:
  `https://www.googleapis.com/auth/directory.readonly`

### Option B: authorized-user OAuth

Use this for a personal Drive, testing, or an operator-run process.

1. Configure the OAuth consent screen in a Google Cloud project.
2. Keep the application in Testing unless publication is actually required.
3. Add the operator account as a test user.
4. Create a Desktop OAuth client.
5. Complete the local OAuth flow and save authorized-user JSON to an ignored
   local path.
6. Leave `google.delegated_user` unset.

The authorized-user JSON must contain grants for:

- `openid`
- `https://www.googleapis.com/auth/userinfo.email`
- `https://www.googleapis.com/auth/userinfo.profile`
- `https://www.googleapis.com/auth/drive`
- `https://www.googleapis.com/auth/spreadsheets`
- `https://www.googleapis.com/auth/drive.activity.readonly` when Activity mode
  is enabled.

The credential loader checks required scopes and fails with a readable error if
the file cannot support the selected service.

## 2. Enable Google APIs

Enable these APIs in the credential-owning Google Cloud project:

- Google Drive API;
- Google Sheets API;
- Drive Activity API when `use_activity_api: true`;
- People API when `use_activity_api: true`.

Example with `gcloud`:

```bash
gcloud services enable \
  drive.googleapis.com \
  sheets.googleapis.com \
  driveactivity.googleapis.com \
  people.googleapis.com \
  --project="<GOOGLE_CLOUD_PROJECT_ID>"
```

The project ID is not a Drive folder ID and is not an OAuth client ID.

## 3. Create the queue Sheet

1. Create a new empty Google Sheet dedicated to moderated deletion.
2. Copy only its spreadsheet ID from the URL.
3. Grant the configured identity Editor access.
4. Do not manually create custom headers. The command creates `pending` and
   `deleted` tabs with the expected schema.

Use a new Sheet if an earlier prototype used a different schema. The command
intentionally refuses to overwrite unknown columns.

## 4. Choose scan roots

Create or identify one or more folders that define the complete allowed scan
scope. Copy their Drive folder IDs into `scan_roots`.

Recommended first setup:

1. create a dedicated test folder;
2. place several synthetic files and nested folders inside it;
3. keep unrelated files in a sibling folder;
4. verify that the sibling folder never appears in dry-run output.

An empty `scan_roots` uses `drive.root_folder_id`. Explicit IDs are safer and
easier to review.

## 5. Configure `data/config.yml`

Copy `data/config.example.yml` to the ignored `data/config.yml`, then fill only
local values:

```yaml
google:
  credentials_file: "data/service-account.json"
  # delegated_user: "operator@example.com"  # service account only

drive:
  id: "<SHARED_DRIVE_ID_OR_EMPTY_FOR_MY_DRIVE>"
  root_folder_id: "<DEFAULT_ROOT_FOLDER_ID>"
  root_folder_name: "Moderated deletion"

commands:
  moderate_delete:
    sheet_id: "<GOOGLE_SHEET_ID>"
    name_marker: "+delete"
    scan_roots:
      - "<ALLOWED_FOLDER_ID>"
    scan_interval_seconds: 300
    max_per_run: 20
    report_csv: "deletions-report.csv"
    allow_folder_delete: false
    use_activity_api: true
    allowed_renamer_domains:
      - "example.com"

output:
  dir: "./data"
```

For authorized-user credentials, point `credentials_file` to the
authorized-user JSON and omit `delegated_user`.

Start with:

- a single test `scan_root`;
- a small `max_per_run`;
- `allow_folder_delete: false`;
- an empty `allowed_renamer_domains` unless actor attribution is already
  verified.

`allowed_renamer_domains` is a server-side policy. If the key is missing or the
list is empty, every actor may request deletion by renaming. If it contains
domains, only exact case-insensitive matches are accepted. `example.com`
accepts `person@example.com`, but not `person@sub.example.com`. Unresolved
actors fail closed. A non-empty list requires `use_activity_api: true`.

## 6. Verify configuration without writes

Run unit tests first:

```bash
pytest -q
```

Preview scan candidates without writing to the Sheet:

```bash
python -m drive_audit.commands \
  --config data/config.yml \
  moderate_delete scan --dry-run
```

Verify:

- only descendants of `scan_roots` appear;
- comments containing `+delete` do not create candidates;
- `+deleted` does not create a candidate;
- a real filename containing `+delete` does create a candidate;
- no trash operation occurs.

## 7. Initialize and inspect the queue

Synchronize once:

```bash
python -m drive_audit.commands \
  --config data/config.yml \
  moderate_delete scan
```

Open the Sheet and inspect the generated `pending` tab.

Before approving anything, verify:

- `file_id`, name, path, and link refer to the same item;
- `scan_root_id` is expected;
- `status` is `pending`;
- `approve` is blank;
- actor fields are populated when Activity mode is enabled.

## 8. Test cancellation

1. Add `+delete` to a synthetic filename.
2. Run `scan`.
3. Confirm a `pending` row exists.
4. Remove `+delete` from the filename.
5. Run `scan` again.
6. Confirm the status becomes `marker_removed`.
7. Confirm `approve` is blank.

Add the marker again and confirm the row returns to `pending` without restoring
the old approval.

## 9. Preview approval

For a synthetic file only:

1. select `yes` in the row's `approve` cell (typed aliases `1` and `да` are
   also accepted);
2. run the preview:

```bash
python -m drive_audit.commands \
  --config data/config.yml \
  moderate_delete apply
```

The command must not trash the item. Review the logs and candidate count.

To refuse a request, select `no` (typed aliases `0` and `нет` are also
accepted). The preview does not mutate the row. On `apply --apply`, the row
becomes `rejected`, the approval cell is cleared, and the item is not trashed.

## 10. Run a controlled live test

After the human explicitly authorizes the live action:

```bash
python -m drive_audit.commands \
  --config data/config.yml \
  moderate_delete apply --apply
```

Verify:

- the synthetic item is in Drive trash;
- the queue row has the expected terminal status;
- the `deleted` tab contains an audit row;
- the CSV report contains the same item;
- the item can be restored through normal Drive trash recovery.

Restore the synthetic item and remove the marker after testing.

## 11. Start periodic scanning

After the one-shot workflow is verified:

```bash
python -m drive_audit.commands \
  --config data/config.yml \
  moderate_delete watch
```

Stop with Ctrl+C. The interval comes from `scan_interval_seconds`. A failed
cycle is logged and a later cycle can retry.

## 12. Rebuild the audit CSV

```bash
python -m drive_audit.commands \
  --config data/config.yml \
  moderate_delete report
```

This rebuilds the configured CSV from the Sheet `deleted` tab.

## Troubleshooting

### `ACCESS_TOKEN_SCOPE_INSUFFICIENT`

The authorized-user token or delegated service account lacks a required scope.
Re-authorize with the scopes listed in this guide. Do not copy tokens into the
configuration manually.

### API has not been used or is disabled

Enable the named API in the same Cloud project that owns the OAuth client or
service account, then retry after propagation.

### `renamer_not_allowed`

Strict mode could not resolve the actor or the actor's domain is outside
`allowed_renamer_domains`. Check:

- Drive Activity and People APIs;
- required scopes;
- domain-wide delegation for service accounts;
- Activity propagation delay;
- the configured allow-list.

Do not bypass this status by manually editing `renamer_email` or
`renamer_domain` in the Sheet. Apply queries the event again. The raw
`renamer_person_id` is a hidden technical field.

### Unexpected Sheet header schema

The immediately previous filename-queue schema is migrated automatically while
preserving approvals. A Sheet from the old comment prototype or a Sheet with
unknown custom columns is not overwritten. Use a new dedicated Sheet or perform
a reviewed explicit migration.

### Actor appears as `people/...`

Run a new scan with Activity mode enabled. People API may return an empty
profile for an external Google account. In that case the resolver uses
`lastModifyingUser` only when the Drive modification time matches the rename
event within five seconds. A successful resolution fills `renamer_name` and
`renamer_email`; the raw resource remains hidden in `renamer_person_id`.

### Marked item is missing

Check:

- the item is a descendant of a configured `scan_root`;
- the full scan completed successfully;
- the marker is in the current filename rather than a comment;
- the marker is not part of a longer token such as `+deleted`;
- Drive Activity has propagated when strict mode is enabled.

### Item is approved but not trashed

Read the row status and logs. Common safe rejections include:

- `marker_removed`;
- `out_of_scope`;
- `already_trashed`;
- `folder_blocked`;
- `no_access`;
- `renamer_not_allowed`;
- `overlap_conflict`.

Fix the underlying condition and require a new human approval.

## Security checklist

- [ ] Credential files are ignored by git.
- [ ] No credential JSON content is pasted into logs, issues, PRs, or chats.
- [ ] The Sheet is dedicated to this workflow.
- [ ] Scan roots are explicit and minimal.
- [ ] `allow_folder_delete` is false unless required.
- [ ] `max_per_run` is appropriate for the deployment.
- [ ] `allowed_renamer_domains` is empty intentionally or contains only exact
      employee email domains.
- [ ] The operator reviews every approval.
- [ ] Live apply always follows a dry-run preview.
- [ ] Trash restoration has been tested with synthetic data.
- [ ] Strict mode remains fail-closed.
