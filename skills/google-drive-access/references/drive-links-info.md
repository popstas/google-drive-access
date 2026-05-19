# drive_links_info — enrich a CSV of folder URLs with Drive metadata

## Purpose

For each Google Drive folder URL in an input CSV, call the Drive API for its metadata (name, mime, parents, owners, created/modified/viewed, permission count, etc.) and write an enriched CSV alongside the original columns. Backed by a local file cache to keep reruns cheap.

## When to use

- Validating freshness of folder URLs exported from CRM (CRM contact → Drive folder).
- Preparing data before `migrate_contact_folders`.
- Lightweight per-contact inventory without scanning the whole drive.

## Inputs

CLI flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--csv-file <path>` | `data/contacts-with-google-folder.csv` | Input CSV |
| `--column <name>` | `Ссылка на Google Drive папку клиента` | Column with URLs |
| `--output <path>` | `data/drive_links_info.csv` | Enriched output CSV |
| `--cache-timeout <seconds>` | `3600` | Folder-metadata cache TTL (`0` disables cache) |
| `--config <path>` | `data/config.yml` | Config (Drive auth) |
| `--debug` | — | Verbose logging |

Added columns: `source_row`, `folder_id`, `folder_name`, `mime_type`, `parents`, `created`, `modified`, `viewed`, `size_bytes`, `owner_emails`, `last_modifying_user_email`, `permissions_count`, `web_view_link`, plus `error` when a row fails.

## Command line

```bash
python -m drive_audit.commands --config data/config.yml drive_links_info \
  --csv-file data/contacts-with-google-folder.csv \
  --column "Ссылка на Google Drive папку клиента" \
  --output data/drive_links_info.csv \
  --cache-timeout 3600

# Disable cache (force fresh API calls)
python -m drive_audit.commands --config data/config.yml drive_links_info \
  --csv-file data/contacts.csv --cache-timeout 0
```

## Outputs

| File | Description |
|------|-------------|
| `data/drive_links_info.csv` (or `--output`) | Original CSV + Drive metadata columns |
| `data/drive_links_info.log` | Operation log |
| `data/cache/folder_metadata/*.json` | Per-folder metadata cache |

## Pitfalls

- Empty/blank URL rows are preserved in the output with empty Drive columns — easy to filter downstream.
- Inaccessible folders produce an `error` value in their row; the rest of the run continues.
- Thousands of URLs may hit Drive rate limits — the cache makes reruns essentially free.
- The default `--column` value is the Russian string `Ссылка на Google Drive папку клиента` — if your CSV uses a different header (English, etc.), pass `--column "<your header>"`; mismatched headers silently produce empty enrichment columns.
