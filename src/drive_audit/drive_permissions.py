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

    def create_anyone_permission(
        self, file_id: str, role: str, expiration_time: str = None
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"type": "anyone", "role": role}
        if expiration_time:
            body["expirationTime"] = expiration_time
        try:
            return (
                self._service.permissions()
                .create(
                    fileId=file_id,
                    supportsAllDrives=True,
                    sendNotificationEmail=False,
                    body=body,
                )
                .execute()
            )
        except HttpError as error:
            logger.error(
                "Failed to create anyone permission for {}: {}", file_id, error
            )
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

    def delete_permission(self, file_id: str, permission_id: str) -> str:
        """
        Delete a permission from a file.

        Args:
            file_id: The ID of the file
            permission_id: The ID of the permission to delete

        Returns:
            "deleted" if successfully deleted, "not_found" if permission not found (404),
            raises exception for other errors

        Raises:
            HttpError: If the deletion fails (except 404 which returns "not_found")
            LocalizedError: If rate limit is exceeded
        """
        try:
            self._service.permissions().delete(
                fileId=file_id,
                permissionId=permission_id,
                supportsAllDrives=True,
            ).execute()
            logger.debug("Deleted permission {} from file {}", permission_id, file_id)
            return "deleted"
        except HttpError as error:
            # Handle 404 (permission not found) gracefully - it might already be deleted
            if hasattr(error, "resp") and error.resp.status == 404:
                logger.warning(
                    "Permission {} not found on file {} (may already be deleted)",
                    permission_id,
                    file_id,
                )
                return "not_found"
            logger.error(
                "Failed to delete permission {} from file {}: {}",
                permission_id,
                file_id,
                error,
            )
            # Check if this is a rate limit error
            if _is_rate_limit_error(error):
                raise LocalizedError("rate_limit_exceeded") from error
            raise
