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
google:
  credentials_file: "data/service-account.json"

drive:
  id: "0AGx8QKiHWRvbUk9PVA"
  root_folder_id: "ROOT_FOLDER_ID" # Defaults to drive_id if not specified
  root_folder_name: "Clients"

scan:
  include_trashed: false
  include_shortcuts: true
  public_folder_name: "public"

output:
  dir: "./data"
  yaml_file: "drive_audit.yml"
  files_csv: "files.csv"
  permissions_csv: "permissions.csv"
```

## Output
Files are saved to the `output.dir` (default `./data`):
- `drive_audit.yml`: Hierarchical structure and full details.
- `files.csv`: Flat list of files with policy flags.
- `permissions.csv`: Detailed permission records.
