"""Route handler for creating client folders."""

from typing import Any, Dict

from loguru import logger

from ..access_service import (
    create_client_folder,
    get_task_and_assignees,
    grant_access,
)
from ..http_utils import LocalizedError


def handle(handler, payload, *, planfix_client, service, drive_config, role):
    """Handle the /create_client_folder route."""
    required_fields = ["contact_id", "folder_name"]
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
        folder_name = str(payload["folder_name"]).strip()
        folder_name_words = folder_name.split()
        name_warning = ""
        if len(folder_name_words) == 1:
            name_warning = " \n" + handler.translate("folder_name_single_word")
        task_id, initial_assignee_ids = get_task_and_assignees(
            planfix_client, contact_id
        )
        folder, created = create_client_folder(service, drive_config, folder_name)
        access_report = grant_access(
            planfix_client,
            service,
            drive_config,
            role,
            task_id,
            initial_assignee_ids,
            folder["id"],
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
    answer = handler.translate(
        "granted_existing",
        granted=handler._format_accounts(granted_accounts),
        existing=handler._format_accounts(existing_accounts),
    )
    folder_url = f"https://drive.google.com/drive/folders/{folder['id']}"
    if created:
        answer_text = (
            handler.translate(
                "folder_created",
                folder_name=folder_name,
                details=answer,
                folder_url=folder_url,
            )
            + name_warning
        )
    else:
        answer_text = (
            handler.translate(
                "client_folder_exists",
                folder_url=folder_url,
                details=answer,
            )
            + name_warning
        )
    handler.send_json(
        200,
        {
            "answer": answer_text,
            "folder_id": folder["id"],
            "folder_url": folder_url,
            "granted_accounts": granted_accounts,
            "existing_accounts": existing_accounts,
        },
    )
