import logging
from typing import Any, Dict, Generator, List, Optional

from googleapiclient.errors import HttpError

from .drive_cache import (
    DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT,
    ListFolderChildrenCache,
)
from .drive_permissions import DrivePermissions

logger = logging.getLogger(__name__)


class DriveFiles:
    def __init__(
        self,
        service,
        cache: Optional[ListFolderChildrenCache] = None,
        permissions: Optional[DrivePermissions] = None,
    ):
        self._service = service
        self._cache = cache or ListFolderChildrenCache()
        self._permissions = permissions or DrivePermissions(service)

    @staticmethod
    def _build_drive_scoping_kwargs(drive_id: str) -> Dict[str, Any]:
        if drive_id:
            return {
                "corpora": "drive",
                "driveId": drive_id,
                "includeItemsFromAllDrives": True,
                "supportsAllDrives": True,
            }

        return {"corpora": "user"}

    def list_files(
        self, drive_id: str, page_size: int = 1000, limit: Optional[int] = None
    ) -> Generator[Dict[str, Any], None, None]:
        page_token = None
        query = "trashed = false"
        count = 0

        fields = "nextPageToken, files(id, name, mimeType, parents, createdTime, modifiedTime, viewedByMeTime, owners, lastModifyingUser, trashed, starred, size, shortcutDetails)"

        while True:
            try:
                current_page_size = page_size
                if limit and (limit - count) < page_size:
                    current_page_size = limit - count

                request_kwargs = {
                    **self._build_drive_scoping_kwargs(drive_id),
                    "q": query,
                    "pageSize": current_page_size,
                    "fields": fields,
                    "pageToken": page_token,
                }

                response = self._service.files().list(**request_kwargs).execute()

                for file in response.get("files", []):
                    yield file
                    count += 1
                    if limit and count >= limit:
                        return

                page_token = response.get("nextPageToken", None)
                if page_token is None:
                    break
            except HttpError as error:
                logger.error("An error occurred while listing files: %s", error)
                raise

    def find_child_folder(
        self, parent_id: str, name: str, drive_id: str
    ) -> Optional[Dict[str, Any]]:
        query = (
            f"'{parent_id}' in parents and "
            "mimeType = 'application/vnd.google-apps.folder' and "
            f"name = '{name}' and trashed = false"
        )
        try:
            request_kwargs = {
                **self._build_drive_scoping_kwargs(drive_id),
                "q": query,
                "fields": "files(id, name)",
            }

            response = self._service.files().list(**request_kwargs).execute()
            files = response.get("files", [])
            if files:
                return files[0]
            return None
        except HttpError as error:
            logger.error(
                "Failed to search for folder %s under %s: %s", name, parent_id, error
            )
            raise

    def create_folder(self, parent_id: str, name: str, drive_id: str) -> Dict[str, Any]:
        body = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        if drive_id:
            body["driveId"] = drive_id
        try:
            return (
                self._service.files()
                .create(body=body, supportsAllDrives=bool(drive_id), fields="id, name")
                .execute()
            )
        except HttpError as error:
            logger.error(
                "Failed to create folder %s under %s: %s", name, parent_id, error
            )
            raise

    def ensure_public_subdir(
        self, parent_id: str, subdir_name: str, drive_id: str
    ) -> Dict[str, Any]:
        try:
            existing_folder = self.find_child_folder(parent_id, subdir_name, drive_id)
        except HttpError as error:
            logger.warning(
                "Failed to look up public subdir '%s' under %s: %s",
                subdir_name,
                parent_id,
                error,
            )
            existing_folder = None
        if existing_folder:
            logger.info(
                "Public subdir '%s' already exists under %s", subdir_name, parent_id
            )
            folder = existing_folder
        else:
            logger.info("Creating public subdir '%s' under %s", subdir_name, parent_id)
            folder = self.create_folder(parent_id, subdir_name, drive_id)

        self._permissions.ensure_public_permission(folder["id"])
        return folder

    def list_folder_children(
        self,
        folder_id: str,
        drive_id: str,
        page_size: int = 100,
        cache_timeout_seconds: int = DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT,
    ) -> Generator[Dict[str, Any], None, None]:
        cached_files = self._cache.get_cached_children(
            drive_id, folder_id, page_size, cache_timeout_seconds
        )
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
                    **self._build_drive_scoping_kwargs(drive_id),
                    "q": query,
                    "pageSize": page_size,
                    "fields": fields,
                    "pageToken": page_token,
                }

                response = self._service.files().list(**request_kwargs).execute()

                for file in response.get("files", []):
                    fetched_files.append(file)
                    yield file

                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            except HttpError as error:
                logger.error(
                    "An error occurred while listing children for %s: %s. Returning partial results.",
                    folder_id,
                    error,
                )
                break

        self._cache.store_cached_children(
            drive_id, folder_id, page_size, fetched_files, cache_timeout_seconds
        )

    def move_file(
        self,
        file_id: str,
        new_parent_id: str,
        current_parents: List[str],
        drive_id: str = "",
    ) -> Dict[str, Any]:
        remove_parents = ",".join(str(parent) for parent in current_parents)
        try:
            updated = (
                self._service.files()
                .update(
                    fileId=file_id,
                    addParents=new_parent_id,
                    removeParents=remove_parents,
                    supportsAllDrives=True,
                    fields="id, parents",
                )
                .execute()
            )
        except HttpError as error:
            logger.error(
                "Failed to move file %s to %s: %s", file_id, new_parent_id, error
            )
            raise

        self._cache.reset(new_parent_id, drive_id)
        for parent_id in current_parents:
            self._cache.reset(parent_id, drive_id)

        return updated
