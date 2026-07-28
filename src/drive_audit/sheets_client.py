"""Narrow Google Sheets client for the filename-based deletion queue."""

from typing import Any, Dict, Iterable, List, Optional, Set

from googleapiclient.discovery import build
from loguru import logger

from .credentials import load_credentials
from .model import DriveConfig

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

PENDING_TAB = "pending"
DELETED_TAB = "deleted"

PENDING_HEADERS_V1 = [
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

DELETED_HEADERS_V1 = [
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

PENDING_HEADERS = [
    "approve",
    "status",
    "previous_name",
    "current_name",
    "item_type",
    "link",
    "renamer_name",
    "renamer_email",
    "renamed_at",
    "path",
    "created_at",
    "modified_at",
    "size_bytes",
    "file_id",
    "scan_root_id",
    "renamer_domain",
    "renamer_person_id",
]

DELETED_HEADERS = [
    "deleted_at",
    "approved_value",
    "previous_name",
    "current_name",
    "item_type",
    "link",
    "renamer_name",
    "renamer_email",
    "renamed_at",
    "path",
    "created_at",
    "modified_at",
    "file_id",
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

    @staticmethod
    def _legacy_actor_fields(value: str) -> Dict[str, str]:
        if "@" in value:
            return {"renamer_email": value}
        if value.startswith("people/"):
            return {"renamer_person_id": value}
        return {"renamer_name": value} if value else {}

    @classmethod
    def _migrate_pending_v1(cls, row: Dict[str, str]) -> Dict[str, str]:
        migrated = {
            "approve": row.get("approve", ""),
            "status": row.get("status", ""),
            "previous_name": row.get("previous_name", ""),
            "current_name": row.get("name", ""),
            "item_type": row.get("item_type", ""),
            "link": row.get("link", ""),
            "renamed_at": row.get("renamed_at", ""),
            "path": row.get("path", ""),
            "created_at": row.get("created", ""),
            "modified_at": row.get("modified", ""),
            "size_bytes": row.get("size", ""),
            "file_id": row.get("file_id", ""),
            "scan_root_id": row.get("scan_root_id", ""),
            "renamer_domain": row.get("renamer_domain", ""),
        }
        migrated.update(cls._legacy_actor_fields(row.get("renamed_by", "")))
        return migrated

    @classmethod
    def _migrate_deleted_v1(cls, row: Dict[str, str]) -> Dict[str, str]:
        migrated = {
            "deleted_at": row.get("deleted_at", ""),
            "approved_value": row.get("approved_value", ""),
            "previous_name": "",
            "current_name": row.get("name", ""),
            "item_type": row.get("item_type", ""),
            "link": "",
            "renamed_at": row.get("renamed_at", ""),
            "path": row.get("path", ""),
            "created_at": row.get("created", ""),
            "modified_at": row.get("modified", ""),
            "file_id": row.get("file_id", ""),
        }
        migrated.update(cls._legacy_actor_fields(row.get("renamed_by", "")))
        return migrated

    def _ensure_header_schema(
        self,
        tab: str,
        expected_headers: List[str],
        legacy_headers: List[str],
        migrate_row,
    ) -> bool:
        values = self._read_values(tab)
        if not values:
            self._replace_tab(tab, expected_headers, [])
            return True
        if values[0] == expected_headers:
            return False
        if values[0] == legacy_headers:
            legacy_rows = self._rows_as_dicts(values)
            self._replace_tab(
                tab,
                expected_headers,
                [migrate_row(row) for row in legacy_rows],
            )
            logger.info("Migrated {} queue schema to moderator layout", tab)
            return True

        raise ValueError(
            f"Unexpected {tab} header schema. Expected {expected_headers}, "
            f"got {values[0]}. Use a new Sheet or migrate it explicitly."
        )

    @staticmethod
    def _dimension_request(
        sheet_id: int,
        start_index: int,
        pixel_size: int,
    ) -> Dict[str, Any]:
        return {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": start_index,
                    "endIndex": start_index + 1,
                },
                "properties": {"pixelSize": pixel_size},
                "fields": "pixelSize",
            }
        }

    @classmethod
    def _format_requests(
        cls,
        sheet_id: int,
        headers: List[str],
        widths: List[int],
        *,
        row_count: int,
        frozen_columns: int,
        hidden_start: Optional[int] = None,
        approve_column: Optional[int] = None,
        status_column: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        requests: List[Dict[str, Any]] = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(headers),
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.91,
                                "green": 0.93,
                                "blue": 0.95,
                            },
                            "textFormat": {
                                "bold": True,
                                "foregroundColor": {
                                    "red": 0.13,
                                    "green": 0.14,
                                    "blue": 0.16,
                                },
                            },
                            "verticalAlignment": "MIDDLE",
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {
                            "frozenRowCount": 1,
                            "frozenColumnCount": frozen_columns,
                        },
                    },
                    "fields": (
                        "gridProperties.frozenRowCount,"
                        "gridProperties.frozenColumnCount"
                    ),
                }
            },
            {
                "setBasicFilter": {
                    "filter": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": row_count,
                            "startColumnIndex": 0,
                            "endColumnIndex": len(headers),
                        }
                    }
                }
            },
        ]
        requests.extend(
            cls._dimension_request(sheet_id, index, width)
            for index, width in enumerate(widths)
        )

        if hidden_start is not None:
            requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": hidden_start,
                            "endIndex": len(headers),
                        },
                        "properties": {"hiddenByUser": True},
                        "fields": "hiddenByUser",
                    }
                }
            )
        if approve_column is not None:
            requests.append(
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": row_count,
                            "startColumnIndex": approve_column,
                            "endColumnIndex": approve_column + 1,
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [
                                    {"userEnteredValue": "yes"},
                                    {"userEnteredValue": "no"},
                                ],
                            },
                            "strict": False,
                            "showCustomUi": True,
                        },
                    }
                }
            )
        if status_column is not None:
            data_range = {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": row_count,
                "startColumnIndex": 0,
                "endColumnIndex": len(headers),
            }
            rules = [
                (
                    f'=${_column_letter(status_column)}2="pending"',
                    {"red": 1.0, "green": 0.96, "blue": 0.78},
                ),
                (
                    (
                        f'=OR(${_column_letter(status_column)}2="error",'
                        f'${_column_letter(status_column)}2="out_of_scope",'
                        f'${_column_letter(status_column)}2="no_access",'
                        f"${_column_letter(status_column)}2="
                        '"renamer_not_allowed",'
                        f'${_column_letter(status_column)}2="overlap_conflict")'
                    ),
                    {"red": 0.98, "green": 0.82, "blue": 0.82},
                ),
                (
                    f'=${_column_letter(status_column)}2="marker_removed"',
                    {"red": 0.93, "green": 0.93, "blue": 0.93},
                ),
            ]
            for formula, color in rules:
                requests.append(
                    {
                        "addConditionalFormatRule": {
                            "rule": {
                                "ranges": [data_range],
                                "booleanRule": {
                                    "condition": {
                                        "type": "CUSTOM_FORMULA",
                                        "values": [{"userEnteredValue": formula}],
                                    },
                                    "format": {"backgroundColor": color},
                                },
                            },
                            "index": 0,
                        }
                    }
                )
        return requests

    def _format_tabs(self, sheet_properties: Dict[str, Dict[str, Any]]) -> None:
        requests: List[Dict[str, Any]] = []
        pending_properties = sheet_properties.get(PENDING_TAB) or {}
        pending_id = pending_properties.get("sheetId")
        if pending_id is not None:
            requests.extend(
                self._format_requests(
                    int(pending_id),
                    PENDING_HEADERS,
                    [
                        90,
                        135,
                        300,
                        340,
                        90,
                        120,
                        190,
                        230,
                        175,
                        380,
                        175,
                        175,
                        95,
                        220,
                        220,
                        150,
                        220,
                    ],
                    row_count=int(
                        (pending_properties.get("gridProperties") or {}).get(
                            "rowCount", 1000
                        )
                    ),
                    frozen_columns=2,
                    hidden_start=13,
                    approve_column=0,
                    status_column=1,
                )
            )

        deleted_properties = sheet_properties.get(DELETED_TAB) or {}
        deleted_id = deleted_properties.get("sheetId")
        if deleted_id is not None:
            requests.extend(
                self._format_requests(
                    int(deleted_id),
                    DELETED_HEADERS,
                    [
                        175,
                        150,
                        300,
                        340,
                        90,
                        120,
                        190,
                        230,
                        175,
                        380,
                        175,
                        175,
                        220,
                    ],
                    row_count=int(
                        (deleted_properties.get("gridProperties") or {}).get(
                            "rowCount", 1000
                        )
                    ),
                    frozen_columns=0,
                    hidden_start=12,
                )
            )

        if requests:
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self._sheet_id,
                body={"requests": requests},
            ).execute()

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

        pending_changed = self._ensure_header_schema(
            PENDING_TAB,
            PENDING_HEADERS,
            PENDING_HEADERS_V1,
            self._migrate_pending_v1,
        )
        deleted_changed = self._ensure_header_schema(
            DELETED_TAB,
            DELETED_HEADERS,
            DELETED_HEADERS_V1,
            self._migrate_deleted_v1,
        )

        if requests or pending_changed or deleted_changed:
            refreshed = (
                self._service.spreadsheets().get(spreadsheetId=self._sheet_id).execute()
            )
            sheet_properties = {
                str(sheet.get("properties", {}).get("title") or ""): dict(
                    sheet.get("properties", {})
                )
                for sheet in refreshed.get("sheets", [])
                if sheet.get("properties", {}).get("sheetId") is not None
            }
            self._format_tabs(sheet_properties)

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
    "DELETED_HEADERS_V1",
    "DELETED_TAB",
    "PENDING_HEADERS",
    "PENDING_HEADERS_V1",
    "PENDING_TAB",
    "SheetsClient",
    "get_sheets_service",
]
