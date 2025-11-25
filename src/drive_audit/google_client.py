import os
import logging
from typing import Optional, Generator, Any, Dict, List
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from .model import DriveConfig

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/drive']

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

def get_file_permissions(service, file_id: str) -> List[Dict[str, Any]]:
    """Fetches permissions for a specific file."""
    try:
        permissions = []
        page_token = None
        
        while True:
            response = service.permissions().list(
                fileId=file_id,
                supportsAllDrives=True,
                fields='nextPageToken, permissions(id, type, role, emailAddress, domain, displayName, allowFileDiscovery, expirationTime, deleted, permissionDetails)',
                pageToken=page_token
            ).execute()
            
            permissions.extend(response.get('permissions', []))
            
            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
                
        return permissions
    except HttpError as error:
        logger.warning(f"Failed to fetch permissions for file {file_id}: {error}")
        return []

def list_files(service, drive_id: str, page_size: int = 1000, limit: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
    """Iterates over all files in the shared drive."""
    page_token = None
    query = "trashed = false"
    count = 0
    
    # Fields to retrieve - optimized for performance
    # Note: permissions are not returned by files.list() - we need to fetch them separately
    fields = "nextPageToken, files(id, name, mimeType, parents, createdTime, modifiedTime, viewedByMeTime, owners, lastModifyingUser, trashed, starred, size, shortcutDetails)"

    while True:
        try:
            # Adjust page_size if we're near the limit
            current_page_size = page_size
            if limit and (limit - count) < page_size:
                current_page_size = limit - count
            
            response = service.files().list(
                corpora='drive',
                driveId=drive_id,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                q=query,
                pageSize=current_page_size,
                fields=fields,
                pageToken=page_token
            ).execute()

            for file in response.get('files', []):
                yield file
                count += 1
                if limit and count >= limit:
                    return

            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
        except HttpError as error:
            logger.error(f"An error occurred while listing files: {error}")
            # Depending on requirements, we might want to retry or stop.
            # For now, we raise to stop execution on critical error.
            raise


def add_user_permission(service, file_id: str, email: str, role: str) -> Dict[str, Any]:
    """Adds a permission for a user to a file or folder.
    
    Note: The 'organizer' role is only valid at the shared drive level.
    For files/folders within a shared drive, 'organizer' is automatically
    converted to 'fileOrganizer'.
    """
    # Convert 'organizer' to 'fileOrganizer' for files/folders
    # The 'organizer' role can only be used at the drive level, not on individual items
    if role == "organizer":
        role = "fileOrganizer"
        logger.debug(f"Converted role 'organizer' to 'fileOrganizer' for file/folder {file_id}")
    
    try:
        return service.permissions().create(
            fileId=file_id,
            supportsAllDrives=True,
            sendNotificationEmail=False,
            body={
                "type": "user",
                "role": role,
                "emailAddress": email,
            },
        ).execute()
    except HttpError as error:
        logger.error(f"Failed to add permission for {email} on {file_id}: {error}")
        raise


def find_child_folder(service, parent_id: str, name: str, drive_id: str) -> Optional[Dict[str, Any]]:
    """Find a child folder with the given name under the specified parent."""
    query = (
        f"'{parent_id}' in parents and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        f"name = '{name}' and trashed = false"
    )
    try:
        response = service.files().list(
            corpora='drive',
            driveId=drive_id,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            q=query,
            fields='files(id, name)'
        ).execute()
        files = response.get('files', [])
        if files:
            return files[0]
        return None
    except HttpError as error:
        logger.error("Failed to search for folder %s under %s: %s", name, parent_id, error)
        raise


def create_folder(service, parent_id: str, name: str, drive_id: str) -> Dict[str, Any]:
    """Create a folder under the specified parent."""
    body = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
        "driveId": drive_id,
    }
    try:
        return service.files().create(
            body=body,
            supportsAllDrives=True,
            fields='id, name'
        ).execute()
    except HttpError as error:
        logger.error("Failed to create folder %s under %s: %s", name, parent_id, error)
        raise


def ensure_public_permission(service, file_id: str) -> Dict[str, Any]:
    """Ensure a file or folder has an 'anyone with the link' reader permission."""
    permissions = get_file_permissions(service, file_id)
    for permission in permissions:
        if permission.get('type') == 'anyone':
            return permission

    logger.info("Setting public access for %s", file_id)
    try:
        return service.permissions().create(
            fileId=file_id,
            supportsAllDrives=True,
            sendNotificationEmail=False,
            body={
                "type": "anyone",
                "role": "reader",
                "allowFileDiscovery": False,
            },
        ).execute()
    except HttpError as error:
        logger.error("Failed to set public permission for %s: %s", file_id, error)
        raise


def ensure_public_subdir(service, parent_id: str, subdir_name: str, drive_id: str) -> Dict[str, Any]:
    """Ensure the configured public subdirectory exists and is shared publicly."""
    existing_folder = find_child_folder(service, parent_id, subdir_name, drive_id)
    if existing_folder:
        logger.info("Public subdir '%s' already exists under %s", subdir_name, parent_id)
        folder = existing_folder
    else:
        logger.info("Creating public subdir '%s' under %s", subdir_name, parent_id)
        folder = create_folder(service, parent_id, subdir_name, drive_id)

    ensure_public_permission(service, folder['id'])
    return folder
