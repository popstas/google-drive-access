# `moderate_delete` — filename-based moderated deletion

## Purpose

Queue files and folders whose current name contains a configurable marker token
(`+delete` by default), require human approval in Google Sheets, then
move validated items to Drive trash. Comments are never read.

The workflow is reversible and auditable:

- `scan` synchronizes the queue once;
- `watch` repeats scan at `scan_interval_seconds`;
- `apply` previews approved rows by default;
- `apply --apply` trashes approved rows after live validation;
- `report` rebuilds the CSV from the `deleted` tab.

## Configuration

```yaml
commands:
  moderate_delete:
    sheet_id: "<GOOGLE_SHEET_ID>"
    name_marker: "+delete"
    scan_roots: ["<FOLDER_ID>"]
    scan_interval_seconds: 300
    max_per_run: 200
    report_csv: "deletions-report.csv"
    allow_folder_delete: false
    use_activity_api: true
    allowed_renamer_domains:
      - "example.com"
```

| Key | Default | Meaning |
|---|---:|---|
| `sheet_id` | required | Sheet containing `pending` and `deleted` tabs |
| `name_marker` | `+delete` | Case-insensitive token; a trailing letter or digit means no match (`+deleted` is ignored) |
| `scan_roots` | `[]` | Folder IDs to traverse recursively; empty uses `drive.root_folder_id` |
| `scan_interval_seconds` | `300` | Delay between `watch` cycles |
| `max_per_run` | `200` | Maximum eligible items trashed by one apply |
| `report_csv` | `deletions-report.csv` | CSV written under `output.dir` |
| `allow_folder_delete` | `false` | Explicit opt-in for trashing marked folders |
| `use_activity_api` | `false` | Resolve rename actor/time through Activity + People |
| `allowed_renamer_domains` | `[]` | Strict actor-domain allow-list; requires Activity mode |

## Queue synchronization

The scanner lists only descendants of `scan_roots`, without using the general
folder cache. A cycle is applied to the Sheet only after the full traversal
succeeds.

Rows are keyed by `file_id`:

- a newly marked item is appended with `status=pending`;
- an active row is refreshed without losing its current approval;
- removing `+delete` sets `status=marker_removed` and clears `approve`;
- moving/trashing an item out of the scanned tree sets `status=out_of_scope`;
- re-adding the marker changes those statuses back to `pending` and clears old
  approval;
- repeated scans do not duplicate the row.

The `pending` columns are:

`approve, status, previous_name, current_name, item_type, link, renamer_name, renamer_email, renamed_at, path, created_at, modified_at, size_bytes, file_id, scan_root_id, renamer_domain, renamer_person_id`

The moderator-facing fields come first. The header and first two columns are
frozen, filtering and approval dropdowns are enabled, status rows are
highlighted, and technical IDs are hidden at the right.

The immediately previous filename-queue schema is migrated automatically while
preserving approvals. Header validation remains fail-closed for the old
comment-based prototype and unknown custom columns.

## Rename actor and strict domain

With `use_activity_api: true`, the scanner calls Drive Activity v2
`activity.query` with `detail.action_detail_case:RENAME`. It selects the latest
rename whose `newTitle` equals the current marked name and records:

- previous and current names;
- rename timestamp;
- actor identity from Drive Activity;
- email/domain resolved by People API when available;
- a Drive `lastModifyingUser` fallback only when its modification time matches
  the rename event within five seconds.

A non-empty `allowed_renamer_domains` is fail-closed. Unresolved or external
renamers are excluded during scan and rejected again during apply.

Required Cloud setup:

- enable Drive Activity API and People API;
- for a service account, grant isolated scopes `drive.activity.readonly` and
  `directory.readonly`, then configure domain-wide delegation through
  `delegated_user`;
- alternatively, use authorized-user JSON with `drive.activity.readonly`,
  `userinfo.email`, and `userinfo.profile`; leave `delegated_user` unset.

Fresh Activity events can appear with latency. Strict mode therefore might
exclude a newly renamed item until a later scan.

## Apply safety

The Sheet is treated as untrusted input. Immediately before trashing every row,
apply re-fetches Drive metadata and verifies:

- the item still exists and is not already trashed;
- its current name still contains `name_marker`;
- it belongs to the configured Drive and `scan_roots`;
- it has `capabilities.canTrash=true`;
- folders are enabled explicitly;
- an approved folder does not overlap an approved descendant in the same run;
- strict renamer domain still passes, when configured.

Invalid rows are not trashed and receive a status such as `marker_removed`,
`out_of_scope`, `already_trashed`, `folder_blocked`, `no_access`, or
`renamer_not_allowed`. Overlapping folder/descendant approvals receive
`overlap_conflict`. Approval is cleared.

Only rows with `status=pending` and `approve` equal to `yes` or `да`
(case-insensitive, surrounding whitespace ignored) are considered.

## Commands

```bash
python -m drive_audit.commands --config data/config.yml moderate_delete scan
python -m drive_audit.commands --config data/config.yml moderate_delete scan --dry-run

python -m drive_audit.commands --config data/config.yml moderate_delete watch
python -m drive_audit.commands --config data/config.yml moderate_delete watch --dry-run

python -m drive_audit.commands --config data/config.yml moderate_delete apply
python -m drive_audit.commands --config data/config.yml moderate_delete apply --apply

python -m drive_audit.commands --config data/config.yml moderate_delete report
```

Stop `watch` with Ctrl+C.

## Access requirements

- The configured identity needs Editor access to the Sheet.
- It needs sufficient Drive access to list the selected tree.
- It needs Content manager or higher to trash Shared Drive items.
- Folder deletion remains disabled unless `allow_folder_delete: true`.

Use `docs/moderate-delete-setup.md` for service-account and authorized-user
setup, safe dry-run validation, and the human/agent operating checklist.
