"""Narrow Google Sheets client for the filename-based deletion queue."""

from typing import Any, Dict, Iterable, List, Optional, Set

from googleapiclient.discovery import build
from loguru import logger

from .credentials import load_credentials
from .model import DriveConfig

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

PENDING_TAB = "pending"
DELETED_TAB = "deleted"

PENDING_HEADERS = [
    "file_id",
    "item_type",
    "name",
    "path",
    "scan_root_id",
    "created",
    "modified",
    "size",
    "renamed_by",
    "renamer_domain",
    "renamed_at",
    "previous_name",
    "link",
    "status",
    "approve",
]

DELETED_HEADERS = [
    "file_id",
    "item_type",
    "name",
    "path",
    "created",
    "modified",
    "deleted_at",
    "approved_value",
    "renamed_by",
    "renamed_at",
]

TERMINAL_STATUSES = {"trashed", "rejected", "already_trashed", "duplicate"}
REACTIVATABLE_STATUSES = {
    "marker_removed",
    "out_of_scope",
    "already_trashed",
    "renamer_not_allowed",
    "folder_blocked",
    "no_access",
    "error",
    "overlap_conflict",
}


def get_sheets_service(config: DriveConfig):
    """Authenticate and return an isolated Google Sheets v4 service."""
    credentials = load_credentials(config, SHEETS_SCOPES)
    return build("sheets", "v4", credentials=credentials)


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


class SheetsClient:
    """Thin wrapper around the two tabs used by ``moderate_delete``."""

    def __init__(self, service, sheet_id: str):
        self._service = service
        self._sheet_id = sheet_id

    def _values(self):
        return self._service.spreadsheets().values()

    def _read_values(self, tab: str) -> List[List[str]]:
        response = self._values().get(spreadsheetId=self._sheet_id, range=tab).execute()
        return response.get("values", [])

    @staticmethod
    def _rows_as_dicts(values: List[List[str]]) -> List[Dict[str, str]]:
        if not values:
            return []
        headers = values[0]
        return [
            {
                header: (raw[index] if index < len(raw) else "")
                for index, header in enumerate(headers)
            }
            for raw in values[1:]
        ]

    def _replace_tab(
        self, tab: str, headers: List[str], rows: Iterable[Dict[str, Any]]
    ) -> None:
        values = [headers]
        values.extend([str(row.get(header, "")) for header in headers] for row in rows)
        self._values().clear(
            spreadsheetId=self._sheet_id,
            range=tab,
            body={},
        ).execute()
        self._values().update(
            spreadsheetId=self._sheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()

    def _ensure_header_schema(self, tab: str, expected_headers: List[str]) -> None:
        values = self._read_values(tab)
        if not values:
            self._replace_tab(tab, expected_headers, [])
            return
        if values[0] == expected_headers:
            return

        raise ValueError(
            f"Unexpected {tab} header schema. Expected {expected_headers}, "
            f"got {values[0]}. Use a new Sheet or migrate it explicitly."
        )

    def ensure_tabs(self) -> None:
        """Create missing tabs and migrate their header schemas when necessary."""
        metadata = (
            self._service.spreadsheets().get(spreadsheetId=self._sheet_id).execute()
        )
        existing = {
            sheet.get("properties", {}).get("title")
            for sheet in metadata.get("sheets", [])
        }

        requests = []
        for tab in (PENDING_TAB, DELETED_TAB):
            if tab not in existing:
                requests.append({"addSheet": {"properties": {"title": tab}}})
        if requests:
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self._sheet_id,
                body={"requests": requests},
            ).execute()

        self._ensure_header_schema(PENDING_TAB, PENDING_HEADERS)
        self._ensure_header_schema(DELETED_TAB, DELETED_HEADERS)

    def read_pending(self) -> List[Dict[str, str]]:
        return self._rows_as_dicts(self._read_values(PENDING_TAB))

    def sync_pending(
        self,
        candidates: List[Dict[str, Any]],
        scanned_item_ids: Set[str],
        scope_ids: Set[str],
        blocked_statuses: Optional[Dict[str, str]] = None,
    ) -> Dict[str, int]:
        """Synchronize active filename markers with the pending queue.

        Rows are keyed by ``file_id``. Active rows are refreshed, missing markers
        are removed from the actionable queue, and re-added markers are queued
        again with approval cleared.
        """
        values = self._read_values(PENDING_TAB)
        existing = self._rows_as_dicts(values)
        blocked_statuses = blocked_statuses or {}
        candidate_by_id = {
            str(candidate.get("file_id", "")): candidate
            for candidate in candidates
            if candidate.get("file_id")
        }
        stats = {
            "added": 0,
            "updated": 0,
            "marker_removed": 0,
            "out_of_scope": 0,
            "reactivated": 0,
            "deduplicated": 0,
        }

        updates = []
        handled_ids: Set[str] = set()
        for row_number, current in enumerate(existing, start=2):
            file_id = current.get("file_id", "")
            if not file_id:
                continue
            if file_id in handled_ids:
                updates.extend(
                    self._changed_cells(
                        row_number,
                        current,
                        {**current, "status": "duplicate", "approve": ""},
                    )
                )
                stats["deduplicated"] += 1
                continue
            handled_ids.add(file_id)

            candidate = candidate_by_id.pop(file_id, None)
            if candidate is not None:
                status = current.get("status", "pending")
                approve = current.get("approve", "")
                if status in REACTIVATABLE_STATUSES:
                    status = "pending"
                    approve = ""
                    stats["reactivated"] += 1

                merged = {
                    header: candidate.get(header, current.get(header, ""))
                    for header in PENDING_HEADERS
                }
                merged["status"] = status or "pending"
                merged["approve"] = approve
                if any(
                    str(merged.get(header, "")) != str(current.get(header, ""))
                    for header in PENDING_HEADERS
                ):
                    stats["updated"] += 1
                    updates.extend(self._changed_cells(row_number, current, merged))
                continue

            row_scope = current.get("scan_root_id", "")
            should_reconcile = bool(row_scope and row_scope in scope_ids)
            status = current.get("status", "")
            if should_reconcile and status not in TERMINAL_STATUSES:
                new_status = blocked_statuses.get(file_id)
                if not new_status:
                    new_status = (
                        "marker_removed"
                        if file_id in scanned_item_ids
                        else "out_of_scope"
                    )
                if status != new_status or current.get("approve", ""):
                    if new_status in stats:
                        stats[new_status] += 1
                    updates.extend(
                        self._changed_cells(
                            row_number,
                            current,
                            {**current, "status": new_status, "approve": ""},
                        )
                    )

        new_rows = []
        for candidate in candidate_by_id.values():
            row = {header: candidate.get(header, "") for header in PENDING_HEADERS}
            row["status"] = "pending"
            row["approve"] = ""
            new_rows.append(row)
            stats["added"] += 1

        if updates:
            self._values().batchUpdate(
                spreadsheetId=self._sheet_id,
                body={"valueInputOption": "RAW", "data": updates},
            ).execute()
        if new_rows:
            self._values().append(
                spreadsheetId=self._sheet_id,
                range=PENDING_TAB,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={
                    "values": [
                        [str(row.get(header, "")) for header in PENDING_HEADERS]
                        for row in new_rows
                    ]
                },
            ).execute()
        return stats

    @staticmethod
    def _changed_cells(
        row_number: int,
        current: Dict[str, Any],
        updated: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        changes = []
        for column_index, header in enumerate(PENDING_HEADERS):
            old_value = str(current.get(header, ""))
            new_value = str(updated.get(header, ""))
            if old_value == new_value:
                continue
            changes.append(
                {
                    "range": (
                        f"{PENDING_TAB}!{_column_letter(column_index)}" f"{row_number}"
                    ),
                    "values": [[new_value]],
                }
            )
        return changes

    def update_status(
        self, file_id: str, status: str, *, clear_approve: bool = False
    ) -> bool:
        """Update every matching row, optionally clearing its approval."""
        values = self._read_values(PENDING_TAB)
        if not values:
            return False
        headers = values[0]
        try:
            file_index = headers.index("file_id")
            status_index = headers.index("status")
            approve_index = headers.index("approve")
        except ValueError:
            return False

        updates = []
        for offset, raw in enumerate(values[1:], start=2):
            current_file = raw[file_index] if file_index < len(raw) else ""
            if current_file != file_id:
                continue
            updates.append(
                {
                    "range": (f"{PENDING_TAB}!{_column_letter(status_index)}{offset}"),
                    "values": [[status]],
                }
            )
            if clear_approve:
                updates.append(
                    {
                        "range": (
                            f"{PENDING_TAB}!{_column_letter(approve_index)}{offset}"
                        ),
                        "values": [[""]],
                    }
                )

        if not updates:
            return False
        self._values().batchUpdate(
            spreadsheetId=self._sheet_id,
            body={"valueInputOption": "RAW", "data": updates},
        ).execute()
        return True

    def read_deleted(self) -> List[Dict[str, str]]:
        return self._rows_as_dicts(self._read_values(DELETED_TAB))

    def append_deleted(
        self, rows: List[Dict[str, Any]], total: Optional[int] = None
    ) -> int:
        if not rows:
            return 0
        values = [
            [str(row.get(header, "")) for header in DELETED_HEADERS] for row in rows
        ]
        self._values().append(
            spreadsheetId=self._sheet_id,
            range=DELETED_TAB,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()
        if total is not None:
            logger.info(
                "Appended {} rows to deleted (run total {})", len(values), total
            )
        return len(values)


__all__ = [
    "DELETED_HEADERS",
    "DELETED_TAB",
    "PENDING_HEADERS",
    "PENDING_TAB",
    "SheetsClient",
    "get_sheets_service",
]
