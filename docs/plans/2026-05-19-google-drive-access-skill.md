# Google Drive Access Skill

## Overview

Create a Claude Code skill at `skills/google-drive-access/SKILL.md` that documents the project's capabilities so an agent can discover the right CLI command or standalone script for a given task without reading the full source.

The skill is a navigation hub: short top-level SKILL.md with triggers, a command matrix, and setup notes; detailed per-command runbooks live in `skills/google-drive-access/references/` and mirror content from `data/use-cases/`.

Scope (per user clarification):
- CLI commands under `python -m drive_audit.commands ...` and `python -m src.drive_audit.main`
- Standalone scripts in the repo root (`find_*.py`, `check_compare_results.py`, `revert_merge_client_folders.py`)
- HTTP endpoints are out of scope for this skill (already documented in README + `data/use-cases/http-*.md`)
- All examples must be anonymized — no real drive IDs, tokens, emails, or Planfix URLs

## Context (from discovery)

Files/components involved:
- New: `skills/google-drive-access/SKILL.md`
- New: `skills/google-drive-access/references/*.md` (one per CLI command + one per standalone script)
- Source content: `data/use-cases/*.md` (Russian runbooks, 22 files including README)
- Project entry points: `src/drive_audit/main.py`, `src/drive_audit/commands/__main__.py`
- Project README: `README.md` — authoritative reference for configuration

Related patterns found:
- Existing skills (e.g. `~/.claude/skills/changelog-cliff/SKILL.md`) use YAML frontmatter with `name`, `description`, then markdown body with "When to Use" + "Quick Reference" matrix
- The use-cases README already provides a usable matrix structure (command → use-case file → inputs)
- Use-case files are in Russian; skill content will be in English but may reference Russian runbooks via links

Inventory of scenarios to cover (16 total):

CLI commands (11):
1. `audit-scan` (main scan via `src.drive_audit.main`)
2. `move_files_to_public_folder`
3. `move_files_csv`
4. `compare_files`
5. `recheck_files`
6. `migrate_contact_folders`
7. `merge_client_folders`
8. `delete_empty_folders`
9. `drive_links_info`
10. `remove_access`
11. `filter_permissions`

Standalone scripts (5):
1. `find_extra_author_access.py`
2. `find_authors_on_inactive_folders.py`
3. `find_similar_files.py`
4. `check_compare_results.py`
5. `revert_merge_client_folders.py`

## Development Approach

- **Testing approach**: Regular (documentation task — no unit tests required; verification via content review)
- Documentation-only task: no Python code changes, no test changes
- Anonymize every example: replace real drive IDs with `<DRIVE_ID>`, tokens with `<TOKEN>`, emails with `user@example.com`, Planfix URLs with `https://planfix.example.com/...`
- Reference content lives in `references/` so SKILL.md stays compact (skill loader keeps the body in context)
- Each per-command reference: 1 file, ~30–80 lines covering purpose, when to use, inputs, command line, outputs, common pitfalls

## Testing Strategy

- No unit/e2e tests (no source code changes)
- Manual verification: re-read `SKILL.md` and 2–3 sample `references/*.md` to confirm anonymization and correctness
- Lint: ensure YAML frontmatter is parseable (key fields: `name`, `description`)

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix

## What Goes Where

- **Implementation Steps**: file creation + content writing
- **Post-Completion**: optional — sharing the skill, copying it into `~/.claude/skills/` if desired

## Implementation Steps

### Task 1: Skeleton and SKILL.md frontmatter
- [ ] create `skills/google-drive-access/SKILL.md` with YAML frontmatter (`name: google-drive-access`, English `description` with trigger phrases: "google drive audit", "shared drive scan", "drive permissions", "planfix folder", "compare drive files", "client folder")
- [ ] add top-level sections: "When to Use", "Quick Reference" (command matrix), "Setup", "Common Workflows", "Reference Files"
- [ ] manual review — confirm frontmatter parses and section outline is sound

### Task 2: Quick Reference matrix and Setup section
- [ ] add markdown table mapping each scenario → command → reference file → inputs (16 rows total)
- [ ] write "Setup" section: prerequisites (Python 3.11+, service account JSON in `data/service-account.json`, `data/config.yml`), with anonymized config snippet
- [ ] add "Common Workflows" section: 3–4 multi-step recipes (e.g. "audit a drive then move public files", "compare two scans and recheck differences")
- [ ] manual review — verify no real IDs/tokens/emails appear

### Task 3: Reference files for CLI commands
- [ ] create `references/audit-scan.md`, `references/move-files-to-public-folder.md`, `references/move-files-csv.md`, `references/compare-files.md`, `references/recheck-files.md`
- [ ] create `references/migrate-contact-folders.md`, `references/merge-client-folders.md`, `references/delete-empty-folders.md`, `references/drive-links-info.md`, `references/remove-access.md`, `references/filter-permissions.md`
- [ ] each file: Purpose, When to use, Inputs (config keys + CLI flags), Command line example (anonymized), Outputs, Pitfalls/notes
- [ ] manual review — spot-check 2 files for anonymization and accuracy against source use-cases

### Task 4: Reference files for standalone scripts
- [ ] create `references/find-extra-author-access.md`, `references/find-authors-on-inactive-folders.md`, `references/find-similar-files.md`
- [ ] create `references/check-compare-results.md`, `references/revert-merge-client-folders.md`
- [ ] each file: Purpose, When to use, Hardcoded inputs (note that paths often live in `__main__`), Command line, Outputs
- [ ] manual review — spot-check 1 file

### Task 5: Verify acceptance criteria
- [ ] verify SKILL.md frontmatter has `name` and `description` with trigger phrases
- [ ] verify all 16 scenarios appear in the Quick Reference matrix
- [ ] verify each matrix row links to an existing `references/*.md`
- [ ] grep the skill tree for any real drive IDs / Planfix domains / non-example emails — should be empty
- [ ] read SKILL.md end-to-end to confirm it stands alone for an agent picking up the project cold

## Technical Details

SKILL.md frontmatter shape:
```yaml
---
name: google-drive-access
description: <English summary + trigger phrases>
---
```

Anonymization map applied throughout:
- Drive IDs (`0AGx8...`, real values from config.yml) → `<DRIVE_ID>`
- Folder IDs → `<FOLDER_ID>`
- Planfix URLs (`https://api.example.com/...` in README is already a placeholder; keep that style) → `https://planfix.example.com/...`
- Tokens → `<TOKEN>`
- Real emails → `user@example.com`, `science@example.com`, etc.
- Local Windows paths (`S:\projects\...`, `d:\projects\...`) from use-cases → drop or replace with `<repo>`

File layout after completion:
```
skills/google-drive-access/
  SKILL.md
  references/
    audit-scan.md
    move-files-to-public-folder.md
    move-files-csv.md
    compare-files.md
    recheck-files.md
    migrate-contact-folders.md
    merge-client-folders.md
    delete-empty-folders.md
    drive-links-info.md
    remove-access.md
    filter-permissions.md
    find-extra-author-access.md
    find-authors-on-inactive-folders.md
    find-similar-files.md
    check-compare-results.md
    revert-merge-client-folders.md
```

## Post-Completion

**Manual verification** (optional):
- Optionally copy/symlink `skills/google-drive-access/` into `~/.claude/skills/` to test that the skill discovery picks it up
- Try a probe query ("how do I find public files outside the public folder?") and confirm the skill description matches
