# Changelog

## Unreleased — filename-based moderated deletion

This change set is relative to `popstas/google-drive-access` `master` at
`2a417932a39efbeed74c23c30c15a0ef612f6c42`.

### Human-readable overview

Users can now request deletion without receiving permission to delete Drive
content directly. They add `+delete` to a file or folder name. The application
finds those names inside explicitly configured folders and places them in a
Google Sheet for review.

A moderator reviews the queue and writes `yes` or `да` in the `approve` column.
The application previews the operation by default. Only an explicit
`apply --apply` command moves approved items to Google Drive trash. Nothing is
hard-deleted, so normal Drive trash recovery remains available.

Removing `+delete` from the name cancels the request automatically on the next
successful scan. The old approval is cleared and is never silently restored if
the marker is later added again.

### Operator workflow

The new `moderate_delete` command has four actions:

| Action | Result |
|---|---|
| `scan` | Traverse the configured folder trees once and synchronize the Sheet |
| `watch` | Repeat synchronization using `scan_interval_seconds` |
| `apply` | Preview which approved rows are currently safe to trash |
| `apply --apply` | Revalidate and move eligible items to Drive trash |
| `report` | Rebuild the local CSV audit from the Sheet `deleted` tab |

`scan --dry-run` and `watch --dry-run` report candidates without modifying the
Sheet. `apply` is always a preview unless `--apply` is present.

### Marker behavior

- The default marker is the case-insensitive token `+delete`.
- It is read only from the current Drive item name. Drive comments are ignored.
- `report+delete`, `report +delete.docx`, and `+DELETE` match.
- `+deleted` and marker continuations with a letter or digit do not match.
- The marker is configurable through `name_marker`.

### Scoped scanning and queue synchronization

- `scan_roots` accepts one or more Drive folder IDs.
- Traversal is recursive and does not enumerate unrelated sibling trees.
- An empty `scan_roots` falls back to `drive.root_folder_id`.
- The command bypasses the general folder-list cache so marker removal is
  visible on the next successful scan.
- Sheet rows are keyed by immutable Drive `file_id`.
- Repeated scans update existing rows instead of appending duplicates.
- The Sheet is synchronized only after the complete traversal succeeds.
- A missing or inaccessible scan root fails the cycle without reconciling old
  queue rows from incomplete data.

Queue lifecycle changes:

| Event | Queue result |
|---|---|
| New marked item | `pending`, blank approval |
| Marker removed | `marker_removed`, approval cleared |
| Item moved outside the configured roots | `out_of_scope`, approval cleared |
| Marker added again | Reactivated as `pending`, old approval cleared |
| Duplicate `file_id` row | Extra row becomes `duplicate` |
| Item already in trash | `already_trashed` |
| Folder deletion disabled | `folder_blocked` |
| Renamer cannot be verified in strict mode | `renamer_not_allowed` |

### Live safety checks before trashing

The Sheet is treated as untrusted input. Immediately before every trash
operation, the application re-fetches Drive metadata and verifies:

1. the row still points to an existing Drive item;
2. the current item name still contains the complete marker token;
3. the item is still inside the configured Drive and `scan_roots`;
4. the item is not already trashed;
5. Drive reports `capabilities.canTrash=true`;
6. folders are allowed explicitly through `allow_folder_delete`;
7. an approved folder does not overlap an approved descendant in the same run;
8. the renamer domain still passes strict validation when configured.

This prevents a modified Sheet row from trashing an arbitrary accessible file,
prevents deletion after marker removal or movement outside scope, and avoids
ambiguous parent/child deletion batches.

`max_per_run` limits the number of eligible items processed by one apply.
Failures receive an explicit status and have their approval cleared.

### Rename attribution and strict domain mode

Optional Drive Activity integration records who added the marker and when:

- Drive Activity v2 is queried with
  `detail.action_detail_case:RENAME`;
- the latest rename whose `newTitle` equals the current marked name is used;
- People API resolves the actor's email and display name;
- the queue stores `previous_name`, `renamed_by`, `renamer_domain`, and
  `renamed_at`.

When `allowed_renamer_domains` is non-empty, the feature fails closed:

- unresolved actors are not queued;
- actors outside the allow-list are not queued;
- the actor/domain is queried again immediately before apply;
- Activity or People API errors prevent trashing.

Drive Activity can publish a new rename with a short delay. A strict scan may
therefore reject a newly renamed item until a later cycle.

### Authentication changes

Google API service factories now accept two credential formats:

1. service-account JSON, including optional domain-wide delegation;
2. authorized-user OAuth JSON with the required granted scopes.

The loader checks the JSON `type`, validates authorized-user scopes, and rejects
`delegated_user` with authorized-user credentials. People API uses:

- `directory.readonly` for delegated service accounts;
- `userinfo.email` and `userinfo.profile` for authorized users.

Drive, Sheets, Drive Activity, and People services remain isolated service
clients, but they share the credential-type validation.

### Configuration additions

`commands.moderate_delete` accepts:

| Key | Default | Purpose |
|---|---:|---|
| `sheet_id` | required | Google Sheet used for `pending` and `deleted` tabs |
| `name_marker` | `+delete` | Case-insensitive filename marker |
| `scan_roots` | `[]` | Folder IDs to traverse recursively |
| `scan_interval_seconds` | `300` | Delay between `watch` cycles |
| `max_per_run` | `200` | Apply safety limit |
| `report_csv` | `deletions-report.csv` | Audit CSV under `output.dir` |
| `allow_folder_delete` | `false` | Explicit folder-trash opt-in |
| `use_activity_api` | `false` | Enable rename actor/time resolution |
| `allowed_renamer_domains` | `[]` | Strict renamer-domain allow-list |

Validation rejects an empty `sheet_id`, an empty marker, non-positive scan
intervals, and a domain allow-list without Activity mode.

### Sheet schema and audit trail

The `pending` tab contains:

`file_id, item_type, name, path, scan_root_id, created, modified, size, renamed_by, renamer_domain, renamed_at, previous_name, link, status, approve`

The `deleted` tab contains:

`file_id, item_type, name, path, created, modified, deleted_at, approved_value, renamed_by, renamed_at`

Unknown or legacy header schemas are rejected rather than overwritten. This is
intentional fail-closed behavior. Operators should use a new Sheet or perform
an explicit migration.

After a successful trash operation, the audit is written to both the Sheet and
the configured CSV. Audit-write errors are surfaced even when Drive already
accepted the trash operation.

### Code-level changes

- `src/drive_audit/commands/moderate_delete.py`
  - implements scan, watch, apply, report, marker parsing, queue reconciliation,
    scope verification, folder-overlap detection, and audit generation;
- `src/drive_audit/sheets_client.py`
  - owns the narrow Sheets v4 queue client and fail-closed schema validation;
- `src/drive_audit/drive_activity.py`
  - resolves rename events and People profiles with per-scan caching;
- `src/drive_audit/credentials.py`
  - loads service-account or authorized-user credentials and checks scopes;
- `src/drive_audit/drive_files.py`
  - adds reversible `files.update(..., trashed=True)` support;
- `src/drive_audit/config_loader.py` and `model.py`
  - add the typed `ModerateDeleteConfig`;
- `src/drive_audit/commands/__init__.py`
  - registers the new CLI command and arguments;
- `README.md`, `data/config.example.yml`, and the agent reference
  - document configuration, operation, authentication, and safety.

### Compatibility

- Existing commands and configuration remain valid.
- No existing command changes its default behavior.
- Folder trashing is disabled by default.
- Activity/People integration is disabled by default.
- Actual trash operations require the new command plus explicit `--apply`.
- The legacy comment-based deletion prototype Sheet is not migrated
  automatically because its schema cannot safely represent filename state.

### Validation

- 158 repository tests pass.
- Black and isort checks pass for all Python source and tests.
- Python bytecode compilation and dependency checks pass.
- A wheel builds successfully.
- CLI parser/help covers all four new actions.
- Field validation covered scoped trees, marker boundaries, cancellation,
  reactivation, watch intervals, dry-run/live apply, tampered Sheet rows,
  folder policies, overlap conflicts, strict domains, Activity/People actor
  resolution, audit recovery, and restoration from Drive trash.

See [docs/moderate-delete-setup.md](docs/moderate-delete-setup.md) for a
credential-safe setup and operating guide.
