"""Route handler for setting client folder access."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from loguru import logger

from ..access_service import (
    extract_folder_id,
    get_task_and_assignees,
    grant_access,
    normalize_assignee_ids,
    normalize_emails,
    parse_assignee_ids,
)
from ..google_client import create_anyone_permission
from ..http_utils import LocalizedError


def handle(
    handler,
    payload,
    *,
    planfix_client,
    service,
    drive_config,
    role,
    share_file_config=None,
):
    """Handle the /set_client_folder_access route."""
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
        contact_id = int(payload["contact_id"])
        folder_id = extract_folder_id(str(payload["folder_url"]))

        emails = normalize_emails(payload.get("email"))

        if emails:
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

        access_report = grant_access(
            planfix_client,
            service,
            drive_config,
            role,
            task_id,
            initial_assignee_ids,
            folder_id,
            email=emails,
        )

        if share_file_config:
            expiration_time = None
            if share_file_config.days > 0:
                expiration_time = (
                    datetime.now(timezone.utc) + timedelta(days=share_file_config.days)
                ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            create_anyone_permission(
                service, folder_id, share_file_config.role, expiration_time
            )
    except LocalizedError as exc:
        handler.send_json(200, {"answer": handler.translate(exc.key, **exc.context)})
        return
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to process request: {}", exc)
        handler.send_json(200, {"answer": handler.translate("internal_server_error")})
        return

    granted_accounts = access_report["granted_accounts"]
    existing_accounts = access_report["existing_accounts"]
    folder_url = str(payload["folder_url"])
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
