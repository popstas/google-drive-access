from typing import Any, Dict

from googleapiclient.discovery import build

from .credentials import load_credentials
from .model import DriveConfig

SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_service(config: DriveConfig):
    """Authenticate and return the Google Drive service."""
    creds = load_credentials(config, SCOPES)
    return build("drive", "v3", credentials=creds)


def get_drive_info(service, drive_id: str) -> Dict[str, Any]:
    """Fetch information about the shared drive or user drive."""
    if not drive_id:
        return service.about().get(fields="user, storageQuota").execute()

    return service.drives().get(driveId=drive_id).execute()
