import logging
from typing import Any, Dict, List

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


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
                "Failed to fetch permissions for file %s: %s", file_id, error
            )
            return []

    def add_user_permission(
        self, file_id: str, email: str, role: str
    ) -> Dict[str, Any]:
        if role == "organizer":
            role = "fileOrganizer"
            logger.debug(
                "Converted role 'organizer' to 'fileOrganizer' for file/folder %s",
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
                "Failed to add permission for %s on %s: %s", email, file_id, error
            )
            raise

    def ensure_public_permission(self, file_id: str) -> Dict[str, Any]:
        permissions = self.get_file_permissions(file_id)
        for permission in permissions:
            if permission.get("type") == "anyone":
                return permission

        logger.info("Setting public access for %s", file_id)
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
            logger.error("Failed to set public permission for %s: %s", file_id, error)
            raise
