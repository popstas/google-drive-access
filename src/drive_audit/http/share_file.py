"""Route handler for sharing a file via 'anyone with the link'."""

from datetime import datetime, timedelta, timezone

from googleapiclient.errors import HttpError
from loguru import logger

from ..access_service import extract_file_id
from ..google_client import (
    create_anyone_permission,
    get_file_metadata,
    get_file_permissions,
)
from ..http_utils import LocalizedError


def handle(handler, payload, *, service, drive_config, share_file_config):
    """Handle the /share_file route."""
    required_fields = ["document_url"]
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
        file_id = extract_file_id(str(payload["document_url"]))

        try:
            metadata = get_file_metadata(service, file_id)
        except HttpError as error:
            if hasattr(error, "resp") and error.resp.status == 404:
                handler.send_json(
                    200, {"answer": handler.translate("share_file_not_found")}
                )
                return
            raise

        if metadata.get("driveId") != drive_config.drive_id:
            handler.send_json(
                200, {"answer": handler.translate("share_file_outside_drive")}
            )
            return

        permissions = get_file_permissions(service, file_id)
        anyone_perm = next(
            (p for p in permissions if p.get("type") == "anyone"), None
        )
        if anyone_perm:
            handler.send_json(
                200,
                {
                    "answer": handler.translate(
                        "share_file_already_shared",
                        role=anyone_perm.get("role", "unknown"),
                    )
                },
            )
            return

        role = share_file_config.role
        days = share_file_config.days
        expiration_time = None
        if days > 0:
            expiration_time = (
                datetime.now(timezone.utc) + timedelta(days=days)
            ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        create_anyone_permission(service, file_id, role, expiration_time)

        if days > 0:
            answer = handler.translate(
                "share_file_shared", days=days, role=role
            )
        else:
            answer = handler.translate(
                "share_file_shared_no_expire", role=role
            )

    except LocalizedError as exc:
        handler.send_json(200, {"answer": handler.translate(exc.key, **exc.context)})
        return
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to process share_file request: {}", exc)
        handler.send_json(200, {"answer": handler.translate("internal_server_error")})
        return

    handler.send_json(200, {"answer": answer})
