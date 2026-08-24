# Google Drive Audit CLI

CLI utility for auditing Google Shared Drives. It scans files, analyzes permissions, and exports the results to YAML and CSV.

## Features
- Connects to a specific Google Shared Drive.
- Scans all files and folders (excluding trashed).
- Reconstructs folder structure and paths.
- Analyzes permissions (public access, domain access, inheritance).
- Checks for policy violations (e.g., public files outside `public` folders).
- Exports data to `drive_audit.yml`, `files.csv`, and `permissions.csv`.

## Requirements
- Python 3.11+
- Google Service Account with access to the target Shared Drive.

## Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/popstas/google-drive-access
    cd google-drive-access
    ```

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    # OR using pyproject.toml
    pip install .
    ```

3.  **Configuration**:
    - Create a `data` directory.
    - Place your Service Account JSON key in `data/service-account.json`.
    - Ensure `data/config.yml` is configured correctly (or use CLI args).

## Usage

Basic usage with default config:
```bash
python -m src.drive_audit.main --config data/config.yml
```

Override Drive ID and Root Folder ID:
```bash
python -m src.drive_audit.main --drive-id <YOUR_DRIVE_ID> --root-folder-id <YOUR_ROOT_FOLDER_ID>
```

## Configuration (`data/config.yml`)
```yaml
lang: "en"

# Logging configuration
# Available levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
logLevel: "INFO"

google:
  credentials_file: "data/service-account.json"

drive:
  id: "0AGx8QKiHWRvbUk9PVA"
  root_folder_id: "ROOT_FOLDER_ID" # Defaults to drive_id if not specified
  root_folder_name: "Clients"
  writer_subdir: ""   # subfolder to grant writer access via /share_folder

scan:
  include_trashed: false
  include_shortcuts: true
  collect_permissions: true
  collect_permissions_max_level: null  # null = all depths; N = only depths <= N (1 = client folders only)
  public_subdir: "public"

cache_timeouts:
  list_folder_children: 3600  # cache folder children for 1 hour (seconds)

compare:
  ignore_public_subdir: false  # If true, ignore public_subdir folder itself, but not its children
  normalize_file_names: false  # If true, normalize file/folder names by replacing forbidden characters with '_'
  ignore_format_differences: false  # If true, ignore format mismatches in comparison (same file, different format)
  ignore_duplicate_suffixes: false  # If true, ignore duplicate suffixes like (1), (2), etc. in file names
  ignore_folders: []  # List of folder names to ignore (only folders with children are ignored)
  ignore_empty_folders: false  # If true, ignore empty folders (folders containing no files) in comparisons

commands:
  move_files_to_public_folder:
    file_match:
      - ".*?KP.*?"
      - "^Public Report\\.csv$"
    mimeType_match:
      - "application/vnd.google-apps.spreadsheet"
      - "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  move_files_csv:
    csv_file: "data/move_files.csv"

output:
  dir: "./data"
  yaml_file: "drive_audit.yml"
  files_csv: "files.csv"
  permissions_csv: "permissions.csv"

planfix:
  getChildTasks:
    url: https://api.example.com/tasks
    token: skldjfh
  getManager:
    url: https://api.example.com/manager
    token: skldjfh
  getClientTask:
    url: https://api.example.com/client-task
    token: skldjfh
  role: "writer"

http:
  port: 7587
  token: skldjfh
```

Set `collect_permissions` to `false` if you only need the file list and want to skip fetching sharing permissions to reduce API calls. Permissions exports will be empty when collection is disabled.

Set `collect_permissions_max_level` to an integer to fetch permissions only for files/folders up to that depth under `root_folder_id` (`1` covers only the first-level client folders, `2` adds one level deeper, etc.). Leave it as `null` to fetch permissions for every file. Ignored when `collect_permissions` is `false`.

Set `public_subdir` to the name of a public-facing subfolder you want to enforce under the target folder when using the HTTP server. If the subfolder does not exist, the server will create it and share it publicly (anyone with the link, reader access).

Set `drive.writer_subdir` to the name of a subfolder inside each client folder that `/share_folder` should grant writer access to. The subfolder must already exist — the endpoint does not create it.

Folder child listings are cached per folder for `cache_timeouts.list_folder_children` seconds (default 1 hour) to reduce repeated API calls. The cache is cleared automatically after files are moved between folders. Set the timeout to `0` to disable caching.

## Logging

The project uses [Loguru](https://github.com/Delgan/loguru) for logging, which provides:
- **Colorized console output** with automatic formatting
- **Automatic file rotation** when log files reach 10 MB
- **Compression** of old log files (ZIP format)
- **Retention** of logs for 30 days
- **Rich exception tracking** with full stack traces

Logs are written to:
- `data/app.log` - Main application logs (for CLI and HTTP server)
- `data/move_files_to_public_folder.log` - Logs for the move_files_to_public_folder command
- `data/move_files_csv.log` - Logs for the move_files_csv command
- `data/compare_files.log` - Logs for the compare_files command

Configure the log level in `config.yml` using the `logLevel` field (DEBUG, INFO, WARNING, ERROR, CRITICAL). You can also use the `--debug` flag with CLI commands to enable DEBUG level logging.

Localization:

- Set the top-level `lang` to `en` (default) or `ru` to localize HTTP responses.
- If an unsupported language is provided, the server falls back to English.

## Commands

### move_files_to_public_folder

Move files that sit at the second level of the shared drive (directly inside each client folder under the configured `drive.root_folder_id`) into that client's `public_subdir` when their names match any of the regular expressions listed in `commands.move_files_to_public_folder.file_match` (case-insensitive). When `commands.move_files_to_public_folder.mimeType_match` is provided, a file must match **both** a filename regex and one of the listed MIME types to be moved. (CamelCase `mimeType_match` is also accepted for backward compatibility, but `mime_type_match` is preferred.)

- Uses `ensure_public_subdir` to create and share the public folder **inside each client folder** if it does not exist.
- Writes command logs to `data/move_files_to_public_folder.log` alongside console output.
- Respects the `--dry-run` flag to log intended moves without changing Google Drive.

Run the command:

```bash
python -m drive_audit.commands --config data/config.yml move_files_to_public_folder --dry-run
```

### move_files_csv

Move an explicit set of files listed in a comma-separated manifest (see `data/move_files.csv`). Each manifest row must include `file_name`, `file_id`, and `dest_folder` (target folder ID inside Google Drive). An optional `source_folder` column can help operators review the origin.

- Reads the manifest path from `commands.move_files_csv.csv_file` (overridable via `--csv-file`).
- Uses the provided `dest_folder` directly; public subfolders are not discovered automatically.
- Writes command logs to `data/move_files_csv.log`.
- Supports `--dry-run` to preview all moves without changing Google Drive.

Run the command:

```bash
python -m drive_audit.commands --config data/config.yml move_files_csv --dry-run
```

### compare_files

Compare two CSV exports (such as those produced by `files.csv`) by their `location` column and write the rows that only exist in
one file. Outputs are written to `data/compare_only_new.csv` (rows unique to the new CSV) and `data/compare_only_old.csv` (rows
unique to the old CSV). When comparing, Google-native files and their Office exports are treated as the same item (for example,
`/Client/File` with mime type `application/vnd.google-apps.document` matches `/Client/File.docx`).

Configuration options in `compare` section:
- `ignore_public_subdir`: If true, ignore the public_subdir folder itself (but not its children) in comparisons.
- `normalize_file_names`: If true, normalize file/folder names by replacing forbidden characters with '_'.
- `ignore_format_differences`: If true, ignore format mismatches (same file, different format).
- `ignore_duplicate_suffixes`: If true, ignore duplicate suffixes like (1), (2), etc. in file names.
- `ignore_folders`: List of folder names to ignore. Folders matching names in this list and all their children (files and subfolders) are ignored.
- `ignore_empty_folders`: If true, ignore empty folders (folders containing no files) in comparisons.

Run the command:

```bash
python -m drive_audit.commands --config data/config.yml compare_files data/files_old.csv data/files_new.csv
```

### drive_links_info

Retrieve folder information from Google Drive for URLs listed in a CSV file. This command reads a CSV file with Google Drive folder URLs, extracts the folder IDs, retrieves metadata from the Google Drive API, and saves the results to a new CSV file.

**Caching**: Folder metadata is cached for 3600 seconds (1 hour) by default to improve performance when re-running the command. Cache files are stored in `data/cache/folder_metadata/`.

**All original CSV columns are preserved in the output**, along with the following new columns added:
- `source_row`: Row number from the input CSV (added as the first column)
- `folder_id`: Extracted Google Drive folder ID
- `folder_name`: Name of the folder from Google Drive
- `mime_type`: MIME type of the folder
- `parents`: Parent folder IDs
- `created`: Creation timestamp
- `modified`: Last modification timestamp
- `viewed`: Last viewed timestamp
- `size_bytes`: Size in bytes (if applicable)
- `owner_emails`: Comma-separated list of owner email addresses
- `last_modifying_user_email`: Email of the last user who modified the folder
- `permissions_count`: Number of permissions on the folder
- `web_view_link`: Web link to view the folder
- `error`: Error message (only included if errors occurred)

Note: Rows with empty URLs are still included in the output with empty Drive metadata fields.

Run the command:

```bash
python -m drive_audit.commands --config data/config.yml drive_links_info \
  --csv-file data/contacts-with-google-folder.csv \
  --column "Ссылка на Google Drive папку клиента" \
  --output data/drive_links_info.csv \
  --cache-timeout 3600
```

All arguments are optional and have default values as shown above. Set `--cache-timeout 0` to disable caching.

### filter_permissions

Filter an exported `permissions.csv` by exact `permission_email` matches and write the matching rows to a new CSV. This is a local operation and does not call the Google Drive API.

Run the command:

```bash
python -m drive_audit.commands filter_permissions \
  --emails email@host1.com,email2@example.com \
  --csv-save data/filtered.csv
```

Optional input override:

```bash
python -m drive_audit.commands filter_permissions \
  --emails email@host1.com,email2@example.com \
  --csv-file data/permissions.csv \
  --csv-save data/filtered.csv
```

## Testing and coverage

Install test dependencies with the optional `test` extras and run pytest with coverage enabled:

```bash
pip install .[test]
pytest --cov=src --cov-report=term --cov-report=xml
```

Coverage results are uploaded to Coveralls automatically via the `test` GitHub Actions workflow.

## HTTP server endpoints

The HTTP server (see `src/drive_audit/server.py`) exposes authenticated endpoints for managing client folders. All successful responses use HTTP status 200 and include an `answer` field.

- `POST /set_client_folder_access` — Grants access to an existing folder using Planfix task context.
  - Body fields: always requires `contact_id` and `folder_url`. Provide `task_id` and `assignee_id` to override the client task lookup; otherwise the handler uses `planfix.getClientTask` for the contact to determine the task and assignees.
  - Behavior: loads child tasks from Planfix, collects assignee Google accounts (from the provided task or the client task), optionally ensures the configured `public_subdir` exists under the target folder, and grants the configured Planfix role to those accounts.
  - Link sharing: the folder itself is opened to `anyone` only when `share_file.public_client_folder` is `true` (default `false`). Such a permission never expires — Google Drive supports `expirationTime` on `user` and `group` permissions only — so leaving it on makes every serviced client folder permanently reachable by link. Use `/share_folder` with an explicit `public_access` when a public link is genuinely needed.
- `POST /create_client_folder` — Creates a client folder and applies access based on the client's Planfix task.
  - Body fields: `contact_id`, `folder_name`.
  - Behavior: looks up the client's task via `planfix.getClientTask`. If no task is found, returns `"Client task not found"`. If a folder with the same name already exists under the configured root folder, returns `"Folder already exists"`. Otherwise, creates the folder under the configured root folder, ensures the `public_subdir` if configured, and grants access using the task's assignees and child tasks.
- `POST /share_folder` — Grants writer access to a named subfolder inside the client folder.
  - Body fields: `contact_id`, `folder_url`. Optional: `email` (direct grant, skips Planfix lookup), `task_id` + `assignee_id` (override Planfix lookup; both must be provided together), `public_access` (role string, e.g. `"writer"`, `"reader"`, `"commenter"` — grants "anyone with the link" permission with that role; `true` defaults to `"reader"`), `lang`.
  - Behavior: requires `drive.writer_subdir` to be set in config. Finds the subfolder by that name inside the folder identified by `folder_url`, verifies it is a direct child folder of the client folder, then grants the configured role to the resolved accounts. When `public_access` is provided, also grants "anyone with the link" permission to the subfolder with the specified role. The `public_subdir` is not created inside this subfolder.
  - Error responses: `writer_subdir_not_configured`, `unable_extract_folder_id`, `subfolder_not_found`, `subfolder_not_a_folder`, `subfolder_not_child`.

- `POST /share_file` — Opens one document to "anyone with the link".
  - Body fields: `document_url`.
  - Behavior: resolves the file id from the url, checks the file lives in the configured shared drive, and grants an `anyone` permission with the role and expiry from the `share_file` config section. A file that already has an `anyone` permission is left as is.
  - Documents only: a link pointing at a folder is refused with `share_file_is_folder`. An `anyone` permission on a folder exposes everything inside it, now and later, and it cannot be time-boxed — that is the leak found in client folders on 15.08.2026.
  - Error responses: `unable_extract_file_id`, `share_file_not_found`, `share_file_outside_drive`, `share_file_is_folder`.

All `/set_client_folder_access` and `/share_folder` endpoints accept an optional `lang` field (`"en"` or `"ru"`) to override the server's default response language for that request.

## Output
Files are saved to the `output.dir` (default `./data`):
- `drive_audit.yml`: Hierarchical structure and full details.
- `files.csv`: Flat list of files with policy flags.
- `permissions.csv`: Detailed permission records.

## Claude Code Skill

A Claude Code skill at `skills/google-drive-access/SKILL.md` maps natural-language tasks ("compare two scans", "find authors on inactive folders") to the right CLI command or standalone script. Per-command runbooks live in `skills/google-drive-access/references/`; detailed Russian use-cases remain in `data/use-cases/`.

To use it, copy or symlink `skills/google-drive-access/` into `~/.claude/skills/`.
