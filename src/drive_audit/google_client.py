from typing import Any, Dict, Generator, List, Optional

from loguru import logger

from .drive_cache import (
    DEFAULT_CACHE_ROOT,
    DEFAULT_LIST_CHILDREN_CACHE_DIR,
    DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT,
    ListFolderChildrenCache,
    list_children_cache,
    reset_list_folder_children_cache,
    set_list_folder_children_cache_dir,
)
from .drive_client import get_drive_info, get_service
from .drive_files import DriveFiles
from .drive_permissions import DrivePermissions
from .model import DriveConfig

SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveFacade:
    def __init__(self, service, cache: ListFolderChildrenCache = list_children_cache):
        self.cache = cache
        self.permissions = DrivePermissions(service)
        self.files = DriveFiles(service, cache=cache, permissions=self.permissions)


__all__ = [
    "DEFAULT_CACHE_ROOT",
    "DEFAULT_LIST_CHILDREN_CACHE_DIR",
    "DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT",
    "DriveConfig",
    "add_user_permission",
    "create_anyone_permission",
    "create_folder",
    "delete_folder",
    "delete_permission",
    "ensure_public_permission",
    "ensure_public_subdir",
    "find_child_folder",
    "get_drive_info",
    "get_file_metadata",
    "get_file_permissions",
    "get_service",
    "list_files",
    "list_folder_children",
    "move_file",
    "reset_list_folder_children_cache",
    "set_list_folder_children_cache_dir",
]


def _with_facade(service) -> DriveFacade:
    return DriveFacade(service, cache=list_children_cache)


def list_files(
    service, drive_id: str, page_size: int = 1000, limit: Optional[int] = None
) -> Generator[Dict[str, Any], None, None]:
    facade = _with_facade(service)
    return facade.files.list_files(drive_id, page_size=page_size, limit=limit)


def get_file_permissions(service, file_id: str) -> List[Dict[str, Any]]:
    facade = _with_facade(service)
    return facade.permissions.get_file_permissions(file_id)


def add_user_permission(service, file_id: str, email: str, role: str) -> Dict[str, Any]:
    facade = _with_facade(service)
    return facade.permissions.add_user_permission(file_id, email, role)


def find_child_folder(
    service, parent_id: str, name: str, drive_id: str
) -> Optional[Dict[str, Any]]:
    facade = _with_facade(service)
    return facade.files.find_child_folder(parent_id, name, drive_id)


def create_folder(service, parent_id: str, name: str, drive_id: str) -> Dict[str, Any]:
    facade = _with_facade(service)
    return facade.files.create_folder(parent_id, name, drive_id)


def ensure_public_permission(service, file_id: str) -> Dict[str, Any]:
    facade = _with_facade(service)
    return facade.permissions.ensure_public_permission(file_id)


def ensure_public_subdir(
    service, parent_id: str, subdir_name: str, drive_id: str
) -> Dict[str, Any]:
    facade = _with_facade(service)
    return facade.files.ensure_public_subdir(parent_id, subdir_name, drive_id)


def list_folder_children(
    service,
    folder_id: str,
    drive_id: str,
    page_size: int = 100,
    cache_timeout_seconds: int = DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT,
) -> Generator[Dict[str, Any], None, None]:
    facade = _with_facade(service)
    return facade.files.list_folder_children(
        folder_id,
        drive_id,
        page_size=page_size,
        cache_timeout_seconds=cache_timeout_seconds,
    )


def move_file(
    service,
    file_id: str,
    new_parent_id: str,
    current_parents: List[str],
    drive_id: str = "",
) -> Dict[str, Any]:
    facade = _with_facade(service)
    return facade.files.move_file(file_id, new_parent_id, current_parents, drive_id)


def delete_folder(
    service,
    folder_id: str,
    drive_id: str = "",
) -> None:
    facade = _with_facade(service)
    return facade.files.delete_folder(folder_id, drive_id)


def delete_permission(service, file_id: str, permission_id: str) -> str:
    facade = _with_facade(service)
    return facade.permissions.delete_permission(file_id, permission_id)


def get_file_metadata(service, file_id: str) -> Dict[str, Any]:
    facade = _with_facade(service)
    return facade.files.get_file_metadata(file_id)


def create_anyone_permission(
    service, file_id: str, role: str, expiration_time: str = None
) -> Dict[str, Any]:
    facade = _with_facade(service)
    return facade.permissions.create_anyone_permission(file_id, role, expiration_time)
