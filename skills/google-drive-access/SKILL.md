---
name: google-drive-access
description: Navigation hub for the google-drive-access project. Use when auditing Google Shared Drives, scanning files and permissions, comparing scans, moving files into public folders, migrating Planfix contact folders, merging client folders, removing access, or running standalone debug scripts. Triggers on "google drive audit", "shared drive scan", "drive permissions", "planfix folder", "compare drive files", "client folder", "audit-scan", "move_files_to_public_folder", "merge_client_folders", "find_similar_files".
---

# google-drive-access

Skill for the google-drive-access CLI/HTTP project: maps a task to the right command or standalone script, with anonymized inputs and a pointer to the detailed runbook.

## When to Use

Use this skill when the user is working inside the google-drive-access repository and asks about:

- auditing a Google Shared Drive (file tree, permissions, policy violations)
- moving files into a public subfolder (by regex or via CSV manifest)
- comparing two scans (`files.csv` vs `new_files.csv`) and rechecking diffs
- migrating Planfix contact folders, merging duplicate client folders, deleting empty folders
- listing drive link metadata, removing access by user, filtering permissions CSVs
- one-off standalone scripts in the repo root (`find_*.py`, `check_compare_results.py`, `revert_merge_client_folders.py`)

HTTP endpoints are out of scope for this skill — see `README.md` and `data/use-cases/http-*.md` for those.

## Quick Reference

See the command matrix in the "Quick Reference" section below (populated in Task 2). Each row points to a per-command runbook in `references/`.

## Setup

Prerequisites and anonymized config snippet (populated in Task 2).

## Common Workflows

Multi-step recipes for the most common combinations (populated in Task 2).

## Reference Files

Per-command runbooks live in `references/`:

- CLI commands (one file per command under `python -m drive_audit.commands ...` plus the main scan)
- Standalone scripts (one file per `.py` script in the repo root)

Files are created in Tasks 3 and 4.
