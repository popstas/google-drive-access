# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project Overview

Google Drive Audit CLI - A Python CLI and HTTP server for auditing Google Shared Drives. Scans files, analyzes permissions, detects policy violations (public files outside designated public folders), and exports results to YAML/CSV. Integrates with Planfix CRM for contact folder management.

## Commands

### Running the main audit
```bash
python -m src.drive_audit.main --config data/config.yml
```

### Running specific commands
```bash
python -m drive_audit.commands --config data/config.yml <command> [options]
# Commands: move_files_to_public_folder, move_files_csv, compare_files, recheck_files,
#           migrate_contact_folders, merge_client_folders, delete_empty_folders,
#           drive_links_info, remove_access, filter_permissions
```

### HTTP Server
```bash
python -m drive_audit.server --config data/config.yml
```

### Testing
```bash
pip install .[test]
pytest --cov=src --cov-report=term --cov-report=xml

# Run a single test file
pytest tests/test_scanner.py

# Run a specific test
pytest tests/test_scanner.py::test_function_name -v
```

### Formatting (run before committing)
```bash
black src tests
isort src tests
```

## Architecture

**Entry Points:**
- `src/drive_audit/main.py` - Main CLI for scanning and exporting
- `src/drive_audit/commands/__main__.py` - Command registry (plugin pattern)
- `src/drive_audit/server.py` - HTTP server for folder access management

**Core Modules:**
- `google_client.py` - Facade for Google Drive API operations
- `drive_files.py` - File listing, folder hierarchy, shortcut handling
- `drive_permissions.py` - Permission retrieval and management
- `scanner.py` - Main logic: builds file tree, resolves paths, applies policies
- `policy.py` - Policy enforcement: detects public files outside public folders
- `access_service.py` - Creates folders, grants access, URL ID extraction, Planfix integration
- `http/` - HTTP route handlers package (see `src/drive_audit/http/AGENTS.md`)
- `http_utils.py` - Shared HTTP utilities (JsonRequestHandler, LocalizedError) — used by both http/ and non-HTTP modules

**Data Flow:**
```
CLI/HTTP → Config Loader → Google Service Init → Scanner (build_file_tree)
    → DriveFiles + DrivePermissions → Apply Policies → Export (YAML/CSV)
```

**Shared Drive Structure:** Level 1 = client folders (by name), Level 2+ = client's files

## Coding Standards

- Use snake_case for variables, functions, and config
- HTTP server always returns 200 status with `"answer"` key in response
- Cover new features with tests
- Add documentation to README.md and new config vars to config.example.yml

## Compare Command Guidelines

When modifying compare logic:
1. Before changes: run `python check_compare_results.py` to establish baseline
2. After changes: run `compare_files`, then `python check_compare_results.py` to verify row counts decreased
3. If counts increased, fix normalization issues before proceeding
4. Run `python find_similar_files.py` to find remaining issues

**Google Format Conversions:** When comparing migrated files, account for Google-to-Office conversions:
- Google Docs → .docx, .odt, .rtf, .pdf, .txt
- Google Sheets → .xlsx, .ods, .csv (first sheet only)
- Google Slides → .pptx, .odp, .pdf
- Google Drawings → .pdf, .jpg, .png, .svg

## Key Files for Common Tasks

- **Adding a new HTTP route:** Create module in `src/drive_audit/http/`, wire in `handler.py` `do_POST` (see `src/drive_audit/http/AGENTS.md`)
- **Adding a new command:** Create module in `src/drive_audit/commands/`, register in `__init__.py`
- **Adding translations:** Update `src/drive_audit/translations.py` (both `en` and `ru` sections)
- **Modifying policies:** Edit `src/drive_audit/policy.py`
- **Configuration options:** Add dataclass to `model.py`, builder to `config_loader.py`, load in `server.py`, document in `config.example.yml`
- **Adding Google API operations:** Add method to `drive_files.py` or `drive_permissions.py`, then add facade wrapper in `google_client.py` and update its `__all__`
