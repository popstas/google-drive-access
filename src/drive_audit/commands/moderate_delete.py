"""Moderated deletion driven by a configurable marker in an item's name."""

import csv
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from loguru import logger

from ..config_loader import build_moderate_delete_config
from ..drive_activity import (
    RenameActivityResolver,
    RenameEvent,
    get_activity_service,
    get_people_service,
)
from ..google_client import trash_file
from ..model import DriveConfig, ModerateDeleteConfig
from ..sheets_client import DELETED_HEADERS, SheetsClient, get_sheets_service

FOLDER_MIME = "application/vnd.google-apps.folder"
APPROVE_VALUES = {"yes", "1", "да"}
REJECT_VALUES = {"no", "0", "нет"}

ITEM_FIELDS = (
    "id,name,mimeType,parents,driveId,createdTime,modifiedTime,trashed,size,"
    "capabilities(canTrash),"
    "lastModifyingUser(displayName,emailAddress,permissionId)"
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_marker(name: str, marker: str) -> bool:
    """Match a marker unless it is the prefix of a longer alphanumeric word."""
    if not marker:
        return False

    folded_name = (name or "").casefold()
    folded_marker = marker.casefold()
    start = 0
    while True:
        marker_index = folded_name.find(folded_marker, start)
        if marker_index < 0:
            return False
        marker_end = marker_index + len(folded_marker)
        if marker_end == len(folded_name) or not folded_name[marker_end].isalnum():
            return True
        start = marker_index + 1


def _item_type(metadata: Dict[str, Any]) -> str:
    return "folder" if metadata.get("mimeType") == FOLDER_MIME else "file"


def _item_link(file_id: str, item_type: str) -> str:
    if item_type == "folder":
        return f"https://drive.google.com/drive/folders/{file_id}"
    return f"https://drive.google.com/file/d/{file_id}/view"


def _scan_roots(
    drive_config: DriveConfig, md_config: ModerateDeleteConfig
) -> List[str]:
    configured = [root for root in md_config.scan_roots if root]
    fallback = drive_config.root_folder_id or drive_config.drive_id or "root"
    roots = configured or [fallback]
    return list(dict.fromkeys(roots))


def _drive_scoping_kwargs(drive_id: str) -> Dict[str, Any]:
    if not drive_id:
        return {"corpora": "user"}
    return {
        "corpora": "drive",
        "driveId": drive_id,
        "includeItemsFromAllDrives": True,
        "supportsAllDrives": True,
    }


def get_file_metadata(service, file_id: str) -> Dict[str, Any]:
    """Fetch all fields needed for live apply validation."""
    return (
        service.files()
        .get(
            fileId=file_id,
            supportsAllDrives=True,
            fields=ITEM_FIELDS,
        )
        .execute()
    )


def _list_children(service, folder_id: str, drive_id: str) -> Iterable[Dict[str, Any]]:
    """List direct children without using the general Drive cache.

    A deletion queue must observe fresh names on every cycle. API failures are
    propagated so a partial scan can never remove unseen rows from the queue.
    """
    page_token: Optional[str] = None
    while True:
        request = {
            **_drive_scoping_kwargs(drive_id),
            "q": f"'{folder_id}' in parents and trashed = false",
            "pageSize": 1000,
            "fields": f"nextPageToken,files({ITEM_FIELDS})",
            "pageToken": page_token,
        }
        response = service.files().list(**request).execute()
        yield from response.get("files", []) or []
        page_token = response.get("nextPageToken")
        if not page_token:
            return


def _walk_scoped_items(
    service,
    drive_config: DriveConfig,
    md_config: ModerateDeleteConfig,
) -> Tuple[List[Tuple[Dict[str, Any], str, str]], Set[str], Set[str]]:
    """Return fresh metadata for descendants of the configured scan roots."""
    roots = _scan_roots(drive_config, md_config)
    queue: deque[Tuple[str, str, str]] = deque()
    visited_folders: Set[str] = set()
    scanned_item_ids: Set[str] = set()
    items: List[Tuple[Dict[str, Any], str, str]] = []

    for root_id in roots:
        root = get_file_metadata(service, root_id)
        if root.get("mimeType") != FOLDER_MIME:
            raise ValueError(f"moderate_delete scan root is not a folder: {root_id}")
        if drive_config.drive_id and root.get("driveId") != drive_config.drive_id:
            raise ValueError(
                f"moderate_delete scan root {root_id} is outside configured drive"
            )
        root_path = "/" + str(root.get("name") or root_id)
        queue.append((root_id, root_path, root_id))

    while queue:
        folder_id, folder_path, scan_root_id = queue.popleft()
        if folder_id in visited_folders:
            continue
        visited_folders.add(folder_id)

        for item in _list_children(service, folder_id, drive_config.drive_id):
            file_id = str(item.get("id") or "")
            if not file_id:
                continue
            scanned_item_ids.add(file_id)
            name = str(item.get("name") or "")
            path = f"{folder_path}/{name}"
            items.append((item, path, scan_root_id))
            if item.get("mimeType") == FOLDER_MIME:
                queue.append((file_id, path, scan_root_id))

    return items, scanned_item_ids, set(roots)


def _candidate_row(
    metadata: Dict[str, Any],
    path: str,
    scan_root_id: str,
    rename_event: Optional[RenameEvent],
) -> Dict[str, Any]:
    file_id = str(metadata.get("id") or "")
    item_type = _item_type(metadata)
    return {
        "approve": "",
        "status": "pending",
        "previous_name": rename_event.previous_name if rename_event else "",
        "current_name": metadata.get("name", ""),
        "item_type": item_type,
        "link": _item_link(file_id, item_type),
        "renamer_name": rename_event.renamer_name if rename_event else "",
        "renamer_email": rename_event.renamer_email if rename_event else "",
        "renamed_at": rename_event.renamed_at if rename_event else "",
        "path": path,
        "created_at": metadata.get("createdTime", ""),
        "modified_at": metadata.get("modifiedTime", ""),
        "size_bytes": metadata.get("size", ""),
        "file_id": file_id,
        "scan_root_id": scan_root_id,
        "renamer_domain": rename_event.renamer_domain if rename_event else "",
        "renamer_person_id": rename_event.person_name if rename_event else "",
    }


def _allowed_domains(md_config: ModerateDeleteConfig) -> Set[str]:
    return {
        domain.strip().casefold().lstrip("@").rstrip(".")
        for domain in md_config.allowed_renamer_domains
        if domain and domain.strip()
    }


def _validate_config(md_config: ModerateDeleteConfig) -> None:
    if not md_config.sheet_id:
        raise ValueError("commands.moderate_delete.sheet_id is required")
    if not md_config.name_marker:
        raise ValueError("commands.moderate_delete.name_marker must not be empty")
    if md_config.scan_interval_seconds <= 0:
        raise ValueError(
            "commands.moderate_delete.scan_interval_seconds must be positive"
        )
    allowed_domains = _allowed_domains(md_config)
    if allowed_domains and not md_config.use_activity_api:
        raise ValueError("allowed_renamer_domains requires use_activity_api: true")
    for domain in allowed_domains:
        if (
            not domain
            or "@" in domain
            or any(character.isspace() for character in domain)
        ):
            raise ValueError(
                "allowed_renamer_domains must contain email domains, not addresses"
            )


def scan(
    service,
    sheets_client: SheetsClient,
    drive_config: DriveConfig,
    md_config: ModerateDeleteConfig,
    dry_run: bool = False,
    rename_resolver: Optional[RenameActivityResolver] = None,
) -> List[Dict[str, Any]]:
    """Synchronize items whose current name contains a complete marker token."""
    _validate_config(md_config)
    if rename_resolver is not None and hasattr(rename_resolver, "clear_activity_cache"):
        rename_resolver.clear_activity_cache()
    items, scanned_item_ids, scope_ids = _walk_scoped_items(
        service, drive_config, md_config
    )
    allowed_domains = _allowed_domains(md_config)
    candidates: List[Dict[str, Any]] = []
    blocked_statuses: Dict[str, str] = {}

    for metadata, path, scan_root_id in items:
        name = str(metadata.get("name") or "")
        if not _has_marker(name, md_config.name_marker):
            continue

        rename_event = None
        if rename_resolver is not None:
            rename_event = rename_resolver.resolve_rename(
                str(metadata.get("id") or ""),
                name,
                md_config.name_marker,
                metadata,
            )

        if allowed_domains:
            domain = rename_event.renamer_domain if rename_event else ""
            if domain.lower() not in allowed_domains:
                blocked_statuses[str(metadata.get("id") or "")] = "renamer_not_allowed"
                logger.info(
                    "Renamer domain reject: {} ({}) domain={}",
                    name,
                    metadata.get("id"),
                    domain or None,
                )
                continue

        candidates.append(_candidate_row(metadata, path, scan_root_id, rename_event))

    logger.info(
        "Scanned {} scoped items, found {} names with marker {}",
        len(items),
        len(candidates),
        md_config.name_marker,
    )

    if dry_run:
        for candidate in candidates:
            logger.info(
                "[dry-run] queue {} ({}) renamed_by={} renamed_at={}",
                candidate["current_name"],
                candidate["file_id"],
                candidate["renamer_email"]
                or candidate["renamer_name"]
                or candidate["renamer_person_id"]
                or None,
                candidate["renamed_at"] or None,
            )
        return candidates

    sheets_client.ensure_tabs()
    stats = sheets_client.sync_pending(
        candidates,
        scanned_item_ids=scanned_item_ids,
        scope_ids=scope_ids,
        blocked_statuses=blocked_statuses,
    )
    logger.info("Synchronized pending queue: {}", stats)
    return candidates


def watch(
    service,
    sheets_client: SheetsClient,
    drive_config: DriveConfig,
    md_config: ModerateDeleteConfig,
    *,
    dry_run: bool = False,
    rename_resolver: Optional[RenameActivityResolver] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_cycles: Optional[int] = None,
) -> int:
    """Run periodic scans until interrupted; return completed cycle count."""
    _validate_config(md_config)
    completed = 0
    attempts = 0
    logger.info(
        "Starting moderate_delete watch every {} seconds",
        md_config.scan_interval_seconds,
    )
    while True:
        try:
            attempts += 1
            scan(
                service,
                sheets_client,
                drive_config,
                md_config,
                dry_run=dry_run,
                rename_resolver=rename_resolver,
            )
            completed += 1
        except KeyboardInterrupt:
            logger.info("moderate_delete watch stopped after {} cycles", completed)
            return completed
        except Exception as error:
            logger.exception("moderate_delete watch cycle failed: {}", error)
        if max_cycles is not None and attempts >= max_cycles:
            return completed
        sleep_fn(float(md_config.scan_interval_seconds))


def _report_path(drive_config: DriveConfig, md_config: ModerateDeleteConfig) -> str:
    return os.path.join(drive_config.output_dir, md_config.report_csv)


def _write_report_csv(rows: List[Dict[str, Any]], output_path: str) -> None:
    directory = os.path.dirname(output_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DELETED_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in DELETED_HEADERS})


def _ancestor_ids(
    service,
    metadata: Dict[str, Any],
    parent_cache: Dict[str, Dict[str, Any]],
) -> Optional[Set[str]]:
    queue = deque(metadata.get("parents", []) or [])
    visited: Set[str] = set()
    while queue:
        parent_id = str(queue.popleft())
        if parent_id in visited:
            continue
        visited.add(parent_id)

        parent = parent_cache.get(parent_id)
        if parent is None:
            try:
                parent = (
                    service.files()
                    .get(
                        fileId=parent_id,
                        supportsAllDrives=True,
                        fields="id,parents,driveId",
                    )
                    .execute()
                )
            except Exception:
                return None
            parent_cache[parent_id] = parent
        queue.extend(parent.get("parents", []) or [])
    return visited


def _is_item_in_scope(
    service,
    metadata: Dict[str, Any],
    drive_config: DriveConfig,
    roots: Set[str],
    parent_cache: Dict[str, Dict[str, Any]],
) -> bool:
    if drive_config.drive_id and metadata.get("driveId") != drive_config.drive_id:
        return False
    ancestors = _ancestor_ids(service, metadata, parent_cache)
    return bool(ancestors is not None and ancestors.intersection(roots))


def _deleted_record(
    row: Dict[str, Any], metadata: Dict[str, Any], deleted_at: str
) -> Dict[str, Any]:
    return {
        "deleted_at": deleted_at,
        "approved_value": row.get("approve", ""),
        "previous_name": row.get("previous_name", ""),
        "current_name": metadata.get(
            "name",
            row.get("current_name", ""),
        ),
        "item_type": _item_type(metadata),
        "link": row.get(
            "link",
            _item_link(str(metadata.get("id") or ""), _item_type(metadata)),
        ),
        "renamer_name": row.get("renamer_name", ""),
        "renamer_email": row.get("renamer_email", ""),
        "renamed_at": row.get("renamed_at", ""),
        "path": row.get("path", ""),
        "created_at": metadata.get(
            "createdTime",
            row.get("created_at", ""),
        ),
        "modified_at": metadata.get(
            "modifiedTime",
            row.get("modified_at", ""),
        ),
        "file_id": metadata.get("id", row.get("file_id", "")),
    }


def _set_status(
    sheets_client: SheetsClient,
    file_id: str,
    status: str,
    real_apply: bool,
) -> None:
    if real_apply:
        sheets_client.update_status(file_id, status, clear_approve=True)


def apply(
    service,
    sheets_client: SheetsClient,
    drive_config: DriveConfig,
    md_config: ModerateDeleteConfig,
    apply: bool = False,
    rename_resolver: Optional[RenameActivityResolver] = None,
) -> List[Dict[str, Any]]:
    """Trash approved rows only after revalidating live Drive state."""
    _validate_config(md_config)
    if rename_resolver is not None and hasattr(rename_resolver, "clear_activity_cache"):
        rename_resolver.clear_activity_cache()
    if apply:
        sheets_client.ensure_tabs()

    pending = sheets_client.read_pending()
    decisions: Dict[str, tuple[str, Dict[str, Any]]] = {}
    for row in pending:
        if row.get("status", "").strip().casefold() != "pending":
            continue
        decision = row.get("approve", "").strip().casefold()
        if decision not in APPROVE_VALUES | REJECT_VALUES:
            continue
        file_id = row.get("file_id", "")
        if not file_id:
            continue
        previous = decisions.get(file_id)
        if decision in REJECT_VALUES or previous is None:
            decisions[file_id] = (decision, row)

    approved: List[Dict[str, Any]] = []
    rejected_count = 0
    for file_id, (decision, row) in decisions.items():
        if decision in REJECT_VALUES:
            rejected_count += 1
            if apply:
                logger.info("Rejected queue item {}", file_id)
            else:
                logger.info("[dry-run] would reject queue item {}", file_id)
            _set_status(sheets_client, file_id, "rejected", apply)
            continue
        approved.append(row)

    roots = set(_scan_roots(drive_config, md_config))
    allowed_domains = _allowed_domains(md_config)
    parent_cache: Dict[str, Dict[str, Any]] = {}
    deleted_rows: List[Dict[str, Any]] = []
    eligible_count = 0

    metadata_by_id: Dict[str, Dict[str, Any]] = {}
    for row in approved:
        file_id = row.get("file_id", "")
        try:
            metadata_by_id[file_id] = get_file_metadata(service, file_id)
        except Exception as error:
            logger.warning("Failed to read metadata for {}: {}", file_id, error)
            _set_status(sheets_client, file_id, "error", apply)

    hierarchy_conflicts: Set[str] = set()
    if md_config.allow_folder_delete:
        approved_folder_ids = {
            file_id
            for file_id, metadata in metadata_by_id.items()
            if metadata.get("mimeType") == FOLDER_MIME
        }
        for file_id, metadata in metadata_by_id.items():
            ancestors = _ancestor_ids(service, metadata, parent_cache)
            if ancestors is None:
                continue
            covering_folders = ancestors.intersection(approved_folder_ids)
            if not covering_folders:
                continue
            hierarchy_conflicts.add(file_id)
            hierarchy_conflicts.update(covering_folders)
        for file_id in hierarchy_conflicts:
            logger.warning(
                "Refusing overlapping approved folder/descendant row: {}",
                file_id,
            )
            _set_status(sheets_client, file_id, "overlap_conflict", apply)

    for row in approved:
        file_id = row.get("file_id", "")
        metadata = metadata_by_id.get(file_id)
        if metadata is None or file_id in hierarchy_conflicts:
            continue

        name = str(metadata.get("name") or "")
        if metadata.get("trashed"):
            logger.info("Skipping already trashed item {} ({})", name, file_id)
            _set_status(sheets_client, file_id, "already_trashed", apply)
            continue
        if not _has_marker(name, md_config.name_marker):
            logger.info("Marker removed before apply: {} ({})", name, file_id)
            _set_status(sheets_client, file_id, "marker_removed", apply)
            continue
        if not _is_item_in_scope(service, metadata, drive_config, roots, parent_cache):
            logger.warning("Refusing out-of-scope item {} ({})", name, file_id)
            _set_status(sheets_client, file_id, "out_of_scope", apply)
            continue
        if (
            metadata.get("mimeType") == FOLDER_MIME
            and not md_config.allow_folder_delete
        ):
            logger.warning("Folder deletion is disabled: {} ({})", name, file_id)
            _set_status(sheets_client, file_id, "folder_blocked", apply)
            continue
        if not (metadata.get("capabilities") or {}).get("canTrash", False):
            logger.warning("No permission to trash {} ({})", name, file_id)
            _set_status(sheets_client, file_id, "no_access", apply)
            continue

        rename_event = None
        if allowed_domains:
            if rename_resolver is not None:
                rename_event = rename_resolver.resolve_rename(
                    file_id,
                    name,
                    md_config.name_marker,
                    metadata,
                )
            domain = rename_event.renamer_domain if rename_event else ""
            if domain.casefold().rstrip(".") not in allowed_domains:
                logger.warning(
                    "Refusing untrusted or unresolved renamer for {} ({})",
                    name,
                    file_id,
                )
                _set_status(sheets_client, file_id, "renamer_not_allowed", apply)
                continue

        if md_config.max_per_run > 0 and eligible_count >= md_config.max_per_run:
            break
        eligible_count += 1

        if rename_event is not None:
            row = dict(row)
            row["renamer_name"] = rename_event.renamer_name
            row["renamer_email"] = rename_event.renamer_email
            row["renamed_at"] = rename_event.renamed_at
            row["renamer_person_id"] = rename_event.person_name
        record = _deleted_record(row, metadata, _utcnow_iso())

        if not apply:
            logger.info("[dry-run] would trash {} ({})", name, file_id)
            deleted_rows.append(record)
            continue

        try:
            trash_file(service, file_id)
        except Exception as error:
            logger.error("Failed to trash {} ({}): {}", name, file_id, error)
            _set_status(sheets_client, file_id, "error", True)
            continue

        try:
            sheets_client.update_status(file_id, "trashed", clear_approve=True)
        except Exception as error:
            logger.error(
                "Trashed {} ({}) but failed to update pending status: {}",
                name,
                file_id,
                error,
            )
        deleted_rows.append(record)
        logger.info("Trashed {} ({})", name, file_id)

    if apply and deleted_rows:
        audit_errors = []
        try:
            sheets_client.append_deleted(deleted_rows, total=len(deleted_rows))
        except Exception as error:
            logger.error("Failed to append deletion audit to Sheet: {}", error)
            audit_errors.append(error)
        try:
            _write_report_csv(deleted_rows, _report_path(drive_config, md_config))
        except Exception as error:
            logger.error("Failed to write deletion audit CSV: {}", error)
            audit_errors.append(error)
        if audit_errors:
            raise RuntimeError(
                "Items were trashed but one or more audit writes failed"
            ) from audit_errors[0]

    logger.info(
        "moderate_delete {}: {} items, {} rejected",
        "apply" if apply else "dry-run",
        len(deleted_rows),
        rejected_count,
    )
    return deleted_rows


def report(
    sheets_client: SheetsClient,
    drive_config: DriveConfig,
    md_config: ModerateDeleteConfig,
) -> List[Dict[str, Any]]:
    sheets_client.ensure_tabs()
    rows = sheets_client.read_deleted()
    output_path = _report_path(drive_config, md_config)
    _write_report_csv(rows, output_path)
    logger.info("Rebuilt report with {} rows -> {}", len(rows), output_path)
    return rows


def _rename_resolver(
    drive_config: DriveConfig,
    md_config: ModerateDeleteConfig,
    drive_service,
) -> Optional[RenameActivityResolver]:
    if not md_config.use_activity_api:
        return None
    return RenameActivityResolver(
        get_activity_service(drive_config),
        get_people_service(drive_config),
        drive_service,
    )


def run_moderate_delete(args, config_data, drive_config, service) -> None:
    md_config = build_moderate_delete_config(config_data)
    _validate_config(md_config)
    sheets_service = get_sheets_service(drive_config)
    sheets_client = SheetsClient(sheets_service, md_config.sheet_id)
    resolver = _rename_resolver(drive_config, md_config, service)

    action = args.action
    if action == "scan":
        scan(
            service,
            sheets_client,
            drive_config,
            md_config,
            dry_run=getattr(args, "dry_run", False),
            rename_resolver=resolver,
        )
    elif action == "watch":
        watch(
            service,
            sheets_client,
            drive_config,
            md_config,
            dry_run=getattr(args, "dry_run", False),
            rename_resolver=resolver,
        )
    elif action == "apply":
        apply(
            service,
            sheets_client,
            drive_config,
            md_config,
            apply=getattr(args, "apply", False),
            rename_resolver=resolver,
        )
    elif action == "report":
        report(sheets_client, drive_config, md_config)
    else:
        raise ValueError(f"Unsupported moderate_delete action: {action}")


__all__ = [
    "APPROVE_VALUES",
    "REJECT_VALUES",
    "apply",
    "get_file_metadata",
    "report",
    "run_moderate_delete",
    "scan",
    "watch",
]
