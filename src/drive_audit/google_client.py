import os
import logging
import time
from typing import Optional, Generator, Any, Dict, List, Tuple
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from .model import DriveConfig

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/drive']

_list_folder_children_cache: Dict[Tuple[str, str, int], Tuple[float, List[Dict[str, Any]]]] = {}
DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT = 3600


def _build_drive_scoping_kwargs(drive_id: str) -> Dict[str, Any]:
    if drive_id:
        return {
            "corpora": "drive",
            "driveId": drive_id,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        }

    return {"corpora": "user"}

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
    """Fetches information about the shared drive or user drive."""
    try:
        if not drive_id:
            return service.about().get(fields="user, storageQuota").execute()

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
    """Iterates over all files in the shared or user drive."""
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
            
            request_kwargs = {
                **_build_drive_scoping_kwargs(drive_id),
                "q": query,
                "pageSize": current_page_size,
                "fields": fields,
                "pageToken": page_token,
            }

            response = service.files().list(**request_kwargs).execute()

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
        request_kwargs = {
            **_build_drive_scoping_kwargs(drive_id),
            "q": query,
            "fields": 'files(id, name)',
        }

        response = service.files().list(**request_kwargs).execute()
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
    }
    if drive_id:
        body["driveId"] = drive_id
    try:
        return service.files().create(
            body=body,
            supportsAllDrives=bool(drive_id),
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
    try:
        existing_folder = find_child_folder(service, parent_id, subdir_name, drive_id)
    except HttpError as error:
        logger.warning(
            "Failed to look up public subdir '%s' under %s: %s",
            subdir_name,
            parent_id,
            error,
        )
        existing_folder = None
    if existing_folder:
        logger.info("Public subdir '%s' already exists under %s", subdir_name, parent_id)
        folder = existing_folder
    else:
        logger.info("Creating public subdir '%s' under %s", subdir_name, parent_id)
        folder = create_folder(service, parent_id, subdir_name, drive_id)

    ensure_public_permission(service, folder['id'])
    return folder


def _get_drive_scope(drive_id: str) -> str:
    return drive_id or ""


def reset_list_folder_children_cache(
    folder_id: Optional[str] = None, drive_id: str = "", page_size: Optional[int] = None
) -> None:
    """Clear cached children for a folder (or all caches)."""

    if folder_id is None:
        _list_folder_children_cache.clear()
        return

    drive_scope = _get_drive_scope(drive_id)
    keys_to_delete = [
        key
        for key in _list_folder_children_cache
        if key[1] == folder_id and key[0] == drive_scope and (page_size is None or key[2] == page_size)
    ]

    for key in keys_to_delete:
        _list_folder_children_cache.pop(key, None)


def _get_cached_children(
    drive_id: str, folder_id: str, page_size: int, cache_timeout_seconds: int
) -> Optional[List[Dict[str, Any]]]:
    cache_key = (_get_drive_scope(drive_id), folder_id, page_size)
    cached_value = _list_folder_children_cache.get(cache_key)
    if not cached_value:
        return None

    cached_at, cached_files = cached_value
    if cache_timeout_seconds <= 0:
        return None

    if time.time() - cached_at < cache_timeout_seconds:
        return list(cached_files)

    _list_folder_children_cache.pop(cache_key, None)
    return None


def list_folder_children(
    service,
    folder_id: str,
    drive_id: str,
    page_size: int = 100,
    cache_timeout_seconds: int = DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT,
) -> Generator[Dict[str, Any], None, None]:
    """Yield direct children of a folder, caching results for the configured duration."""
    cached_files = _get_cached_children(drive_id, folder_id, page_size, cache_timeout_seconds)
    if cached_files is not None:
        for file in cached_files:
            yield file
        return

    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    fields = "nextPageToken, files(id, name, mimeType, parents)"
    fetched_files: List[Dict[str, Any]] = []

    while True:
        try:
            request_kwargs = {
                **_build_drive_scoping_kwargs(drive_id),
                "q": query,
                "pageSize": page_size,
                "fields": fields,
                "pageToken": page_token,
            }

            response = service.files().list(**request_kwargs).execute()

            for file in response.get('files', []):
                fetched_files.append(file)
                yield file

            page_token = response.get('nextPageToken')
            if not page_token:
                break
        except HttpError as error:
            logger.error("An error occurred while listing children for %s: %s", folder_id, error)
            raise

    if cache_timeout_seconds > 0:
        cache_key = (_get_drive_scope(drive_id), folder_id, page_size)
        _list_folder_children_cache[cache_key] = (time.time(), list(fetched_files))


def move_file(
    service, file_id: str, new_parent_id: str, current_parents: List[str], drive_id: str = ""
) -> Dict[str, Any]:
    """Move a file to a new parent, removing existing parents and invalidating caches."""
    remove_parents = ','.join(str(parent) for parent in current_parents)
    try:
        updated = service.files().update(
            fileId=file_id,
            addParents=new_parent_id,
            removeParents=remove_parents,
            supportsAllDrives=True,
            fields='id, parents'
        ).execute()
    except HttpError as error:
        logger.error("Failed to move file %s to %s: %s", file_id, new_parent_id, error)
        raise

    reset_list_folder_children_cache(new_parent_id, drive_id)
    for parent_id in current_parents:
        reset_list_folder_children_cache(parent_id, drive_id)

    return updated
