"""Route handler for granting writer access to a configured subfolder."""

import dataclasses
from typing import Any, Dict

from loguru import logger

from ..access_service import (
    extract_folder_id,
    get_task_and_assignees,
    grant_access,
    normalize_assignee_ids,
    parse_assignee_ids,
)
from ..google_client import create_anyone_permission, find_child_folder, get_item_info
from ..http_utils import LocalizedError

_FOLDER_MIME = "application/vnd.google-apps.folder"


def handle(handler, payload, *, planfix_client, service, drive_config, role):
    """Handle the /share_folder route."""
    required_fields = ["contact_id", "folder_url"]
    missing_fields = [field for field in required_fields if field not in payload]
    if missing_fields:
        handler.send_json(
            200,
            {
                "answer": handler.translate(
                    "missing_fields", fields=", ".join(missing_fields)
                )
            },
        )
        return

    try:
        if not drive_config.writer_subdir:
            raise LocalizedError("writer_subdir_not_configured")

        contact_id = int(payload["contact_id"])
        parent_folder_id = extract_folder_id(str(payload["folder_url"]))

        email = payload.get("email")
        if isinstance(email, list):
            email = email[0] if email else None

        if email:
            task_id = 0
            initial_assignee_ids = []
        else:
            has_task_id = "task_id" in payload
            has_assignee_id = "assignee_id" in payload

            if has_task_id and has_assignee_id:
                task_id = int(payload["task_id"])
                initial_assignee_ids = normalize_assignee_ids(
                    parse_assignee_ids(payload["assignee_id"])
                )
            elif not has_task_id and not has_assignee_id:
                task_id, initial_assignee_ids = get_task_and_assignees(
                    planfix_client, contact_id
                )
            else:
                handler.send_json(
                    200,
                    {"answer": handler.translate("task_and_assignee_together")},
                )
                return

        subfolder = find_child_folder(
            service, parent_folder_id, drive_config.writer_subdir, drive_config.drive_id
        )
        if subfolder is None:
            raise LocalizedError("subfolder_not_found", name=drive_config.writer_subdir)

        # Verify the item is a folder and is a direct child of the client folder
        item_info = get_item_info(service, subfolder["id"])
        if item_info.get("mimeType") != _FOLDER_MIME:
            raise LocalizedError("subfolder_not_a_folder", name=drive_config.writer_subdir)
        if parent_folder_id not in item_info.get("parents", []):
            raise LocalizedError("subfolder_not_child")

        subfolder_id = subfolder["id"]
        subfolder_drive_config = dataclasses.replace(drive_config, public_subdir=None)
        access_report = grant_access(
            planfix_client,
            service,
            subfolder_drive_config,
            role,
            task_id,
            initial_assignee_ids,
            subfolder_id,
            email=email,
        )

        public_access = payload.get("public_access")
        if public_access:
            public_role = public_access if isinstance(public_access, str) else "reader"
            create_anyone_permission(service, subfolder_id, public_role, None)
    except LocalizedError as exc:
        handler.send_json(200, {"answer": handler.translate(exc.key, **exc.context)})
        return
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to process request: {}", exc)
        handler.send_json(200, {"answer": handler.translate("internal_server_error")})
        return

    granted_accounts = access_report["granted_accounts"]
    existing_accounts = access_report["existing_accounts"]
    folder_url = f"https://drive.google.com/drive/folders/{subfolder_id}"
    answer = handler.translate(
        "granted_existing",
        granted=handler._format_accounts(granted_accounts),
        existing=handler._format_accounts(existing_accounts),
        folder_url=folder_url,
    )
    handler.send_json(
        200,
        {
            "answer": answer,
            "folder_url": folder_url,
            "granted_accounts": granted_accounts,
            "existing_accounts": existing_accounts,
        },
    )
