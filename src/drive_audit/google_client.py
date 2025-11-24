import os
import logging
from typing import Optional, Generator, Any, Dict
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from .model import DriveConfig

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly', 'https://www.googleapis.com/auth/drive.readonly']

def get_service(config: DriveConfig):
    """Authenticates and returns the Google Drive service."""
    creds = None
    if os.path.exists(config.credentials_file):
        creds = service_account.Credentials.from_service_account_file(
            config.credentials_file, scopes=SCOPES
        )
        if config.delegated_user:
            creds = creds.with_subject(config.delegated_user)
    else:
        raise FileNotFoundError(f"Credentials file not found: {config.credentials_file}")

    return build('drive', 'v3', credentials=creds)

def get_drive_info(service, drive_id: str) -> Dict[str, Any]:
    """Fetches information about the shared drive."""
    try:
        return service.drives().get(driveId=drive_id).execute()
    except HttpError as error:
        logger.error(f"An error occurred: {error}")
        raise

def list_files(service, drive_id: str, page_size: int = 1000) -> Generator[Dict[str, Any], None, None]:
    """Iterates over all files in the shared drive."""
    page_token = None
    query = "trashed = false"
    
    # Fields to retrieve - optimized for performance
    fields = "nextPageToken, files(id, name, mimeType, parents, createdTime, modifiedTime, viewedByMeTime, owners, lastModifyingUser, trashed, starred, size, shortcutDetails, permissions)"

    while True:
        try:
            response = service.files().list(
                corpora='drive',
                driveId=drive_id,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                q=query,
                pageSize=page_size,
                fields=fields,
                pageToken=page_token
            ).execute()

            for file in response.get('files', []):
                yield file

            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
        except HttpError as error:
            logger.error(f"An error occurred while listing files: {error}")
            # Depending on requirements, we might want to retry or stop. 
            # For now, we raise to stop execution on critical error.
            raise
