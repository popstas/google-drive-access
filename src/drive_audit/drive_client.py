import os
from typing import Any, Dict

from google.oauth2 import service_account
from googleapiclient.discovery import build

from .model import DriveConfig

SCOPES = ["https://www.googleapis.com/auth/drive"]

# googleapiclient retries connection errors (e.g. BrokenPipeError on a keep-alive
# socket closed during idle), 5xx and 429. Pass it only to requests that are
# safe to repeat: reads, permissions.create/delete. files.create/update/delete
# are left without retries so a repeat cannot duplicate or fail a write.
DRIVE_API_NUM_RETRIES = 3


def get_service(config: DriveConfig):
    """Authenticate and return the Google Drive service."""
    if not os.path.exists(config.credentials_file):
        raise FileNotFoundError(
            f"Credentials file not found: {config.credentials_file}"
        )

    creds = service_account.Credentials.from_service_account_file(
        config.credentials_file, scopes=SCOPES
    )
    if config.delegated_user:
        creds = creds.with_subject(config.delegated_user)

    return build("drive", "v3", credentials=creds)


def get_drive_info(service, drive_id: str) -> Dict[str, Any]:
    """Fetch information about the shared drive or user drive."""
    if not drive_id:
        return (
            service.about()
            .get(fields="user, storageQuota")
            .execute(num_retries=DRIVE_API_NUM_RETRIES)
        )

    return (
        service.drives()
        .get(driveId=drive_id)
        .execute(num_retries=DRIVE_API_NUM_RETRIES)
    )
