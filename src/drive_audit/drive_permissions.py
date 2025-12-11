from typing import Any, Dict, List

from googleapiclient.errors import HttpError
from loguru import logger

from .http_utils import LocalizedError


def _is_rate_limit_error(error: HttpError) -> bool:
    """Check if HttpError is a rate limit error."""
    # Check status code (rate limit errors are usually 403 or 429)
    if hasattr(error, "resp") and error.resp.status in [403, 429]:
        # Check error content for rate limit keywords
        if hasattr(error, "content"):
            error_content = (
                error.content.decode("utf-8")
                if isinstance(error.content, bytes)
                else str(error.content)
            )
            if (
                "rateLimitExceeded" in error_content
                or "userRateLimitExceeded" in error_content
                or "User rate limit exceeded" in error_content
            ):
                return True
        # Check error_details attribute if available
        error_details = getattr(error, "error_details", [])
        if error_details:
            for detail in error_details:
                if isinstance(detail, dict) and detail.get("reason") in [
                    "userRateLimitExceeded",
                    "rateLimitExceeded",
                ]:
                    return True
    return False


class DrivePermissions:
    def __init__(self, service):
        self._service = service

    def get_file_permissions(self, file_id: str) -> List[Dict[str, Any]]:
        try:
            permissions = []
            page_token = None

            while True:
                response = (
                    self._service.permissions()
                    .list(
                        fileId=file_id,
                        supportsAllDrives=True,
                        fields="nextPageToken, permissions(id, type, role, emailAddress, domain, displayName, allowFileDiscovery, expirationTime, deleted, permissionDetails)",
                        pageToken=page_token,
                    )
                    .execute()
                )

                permissions.extend(response.get("permissions", []))

                page_token = response.get("nextPageToken", None)
                if page_token is None:
                    break

            return permissions
        except HttpError as error:
            logger.warning(
                "Failed to fetch permissions for file {}: {}", file_id, error
            )
            return []

    def add_user_permission(
        self, file_id: str, email: str, role: str
    ) -> Dict[str, Any]:
        if role == "organizer":
            role = "fileOrganizer"
            logger.debug(
                "Converted role 'organizer' to 'fileOrganizer' for file/folder {}",
                file_id,
            )

        try:
            return (
                self._service.permissions()
                .create(
                    fileId=file_id,
                    supportsAllDrives=True,
                    sendNotificationEmail=False,
                    body={
                        "type": "user",
                        "role": role,
                        "emailAddress": email,
                    },
                )
                .execute()
            )
        except HttpError as error:
            logger.error(
                "Failed to add permission for {} on {}: {}", email, file_id, error
            )
            # Check if this is a rate limit error
            if _is_rate_limit_error(error):
                raise LocalizedError("rate_limit_exceeded") from error
            raise

    def ensure_public_permission(self, file_id: str) -> Dict[str, Any]:
        permissions = self.get_file_permissions(file_id)
        for permission in permissions:
            if permission.get("type") == "anyone":
                return permission

        logger.info("Setting public access for {}", file_id)
        try:
            return (
                self._service.permissions()
                .create(
                    fileId=file_id,
                    supportsAllDrives=True,
                    sendNotificationEmail=False,
                    body={
                        "type": "anyone",
                        "role": "reader",
                        "allowFileDiscovery": False,
                    },
                )
                .execute()
            )
        except HttpError as error:
            logger.error("Failed to set public permission for {}: {}", file_id, error)
            # Check if this is a rate limit error
            if _is_rate_limit_error(error):
                raise LocalizedError("rate_limit_exceeded") from error
            raise
