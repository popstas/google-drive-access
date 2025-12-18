import csv
from pathlib import Path
from typing import Dict, Iterable, Set

from loguru import logger


def _parse_emails(emails: str) -> Set[str]:
    items = []
    for part in (emails or "").split(","):
        value = part.strip()
        if value:
            items.append(value.lower())
    return set(items)


def filter_permissions(
    csv_file: Path,
    csv_save: Path,
    permission_emails: Iterable[str],
) -> Dict[str, int]:
    """
    Stream-filter a permissions CSV by `permission_email` and write matching rows.

    Args:
        csv_file: Input permissions CSV path.
        csv_save: Output CSV path.
        permission_emails: Emails to keep (case-insensitive).

    Returns:
        Stats dict with total_rows and matched_rows.
    """
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    emails_set = {email.strip().lower() for email in permission_emails if email.strip()}
    if not emails_set:
        raise ValueError("No emails provided to filter by")

    csv_save.parent.mkdir(parents=True, exist_ok=True)

    total_rows = 0
    matched_rows = 0

    with csv_file.open(encoding="utf-8-sig", newline="") as in_handle:
        reader = csv.DictReader(in_handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV file {csv_file} has no headers")

        if "permission_email" not in reader.fieldnames:
            raise ValueError(
                "CSV must contain 'permission_email' column, got: "
                f"{', '.join(reader.fieldnames)}"
            )

        fieldnames = list(reader.fieldnames)

        with csv_save.open("w", encoding="utf-8", newline="") as out_handle:
            writer = csv.DictWriter(out_handle, fieldnames=fieldnames)
            writer.writeheader()

            for row in reader:
                total_rows += 1
                row_email = (row.get("permission_email") or "").strip().lower()
                if row_email in emails_set:
                    writer.writerow(row)
                    matched_rows += 1

    return {"total_rows": total_rows, "matched_rows": matched_rows}


def run_filter_permissions(
    args, config_data: dict, drive_config, service  # noqa: ARG001
) -> None:
    emails = _parse_emails(args.emails)
    stats = filter_permissions(
        csv_file=Path(args.csv_file),
        csv_save=Path(args.csv_save),
        permission_emails=emails,
    )
    logger.info(
        "Filtered permissions: matched {} / {} rows, saved to {}",
        stats["matched_rows"],
        stats["total_rows"],
        args.csv_save,
    )


__all__ = ["filter_permissions", "run_filter_permissions"]
