import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

DEFAULT_CACHE_ROOT = Path("data/cache")
DEFAULT_LIST_CHILDREN_CACHE_DIR = DEFAULT_CACHE_ROOT / "list_folder_children"
DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT = 3600


class ListFolderChildrenCache:
    def __init__(self, cache_dir: Path = DEFAULT_LIST_CHILDREN_CACHE_DIR):
        self._cache: Dict[Tuple[str, str, int], Tuple[float, List[Dict[str, Any]]]] = {}
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _get_drive_scope(drive_id: str) -> str:
        return drive_id or ""

    def set_cache_dir(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache.clear()

    def reset(
        self,
        folder_id: Optional[str] = None,
        drive_id: str = "",
        page_size: Optional[int] = None,
    ) -> None:
        if folder_id is None:
            self._cache.clear()
            self._clear_cache_dir()
            return

        drive_scope = self._get_drive_scope(drive_id)
        keys_to_delete = [
            key
            for key in self._cache
            if key[1] == folder_id
            and key[0] == drive_scope
            and (page_size is None or key[2] == page_size)
        ]

        for key in keys_to_delete:
            self._cache.pop(key, None)
            self._remove_disk_cache(key)

    def get_cached_children(
        self, drive_id: str, folder_id: str, page_size: int, cache_timeout_seconds: int
    ) -> Optional[List[Dict[str, Any]]]:
        cache_key = (self._get_drive_scope(drive_id), folder_id, page_size)
        cached_value = self._cache.get(cache_key)
        if not cached_value:
            cached_value = self._load_disk_cache(cache_key, cache_timeout_seconds)
            if cached_value:
                self._cache[cache_key] = cached_value

        if cache_timeout_seconds <= 0:
            if cached_value:
                self._cache.pop(cache_key, None)
                self._remove_disk_cache(cache_key)
            return None

        if not cached_value:
            return None

        cached_at, cached_files = cached_value

        if time.time() - cached_at < cache_timeout_seconds:
            return list(cached_files)

        self._cache.pop(cache_key, None)
        self._remove_disk_cache(cache_key)
        return None

    def store_cached_children(
        self,
        drive_id: str,
        folder_id: str,
        page_size: int,
        files: List[Dict[str, Any]],
        cache_timeout_seconds: int,
    ) -> None:
        if cache_timeout_seconds <= 0:
            return

        cache_key = (self._get_drive_scope(drive_id), folder_id, page_size)
        cached_value = (time.time(), list(files))
        self._cache[cache_key] = cached_value
        self._write_disk_cache(cache_key, cached_value)

    def _get_cache_file_path(self, cache_key: Tuple[str, str, int]) -> Path:
        drive_scope, folder_id, page_size = cache_key
        safe_drive_scope = drive_scope or "user"
        safe_folder_id = folder_id.replace(os.sep, "_")
        return self._cache_dir / f"{safe_drive_scope}_{safe_folder_id}_{page_size}.json"

    def _load_disk_cache(
        self, cache_key: Tuple[str, str, int], cache_timeout_seconds: int
    ) -> Optional[Tuple[float, List[Dict[str, Any]]]]:
        cache_file = self._get_cache_file_path(cache_key)
        if not cache_file.exists():
            return None

        try:
            with cache_file.open(encoding="utf-8") as cache_handle:
                payload = json.load(cache_handle)
        except (OSError, json.JSONDecodeError):
            cache_file.unlink(missing_ok=True)
            return None

        cached_at = payload.get("cached_at")
        cached_files = payload.get("files")
        if not isinstance(cached_at, (int, float)) or not isinstance(
            cached_files, list
        ):
            cache_file.unlink(missing_ok=True)
            return None

        if (
            cache_timeout_seconds <= 0
            or time.time() - cached_at >= cache_timeout_seconds
        ):
            cache_file.unlink(missing_ok=True)
            return None

        return cached_at, cached_files

    def _write_disk_cache(
        self,
        cache_key: Tuple[str, str, int],
        cached_value: Tuple[float, List[Dict[str, Any]]],
    ) -> None:
        cache_file = self._get_cache_file_path(cache_key)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cached_at, cached_files = cached_value
        try:
            with cache_file.open("w", encoding="utf-8") as cache_handle:
                json.dump({"cached_at": cached_at, "files": cached_files}, cache_handle)
        except OSError:
            logger.warning("Failed to persist cache file {}", cache_file)

    def _remove_disk_cache(self, cache_key: Tuple[str, str, int]) -> None:
        cache_file = self._get_cache_file_path(cache_key)
        cache_file.unlink(missing_ok=True)

    def _clear_cache_dir(self) -> None:
        if not self._cache_dir.exists():
            return

        for cache_file in self._cache_dir.glob("*.json"):
            cache_file.unlink(missing_ok=True)


def set_list_folder_children_cache_dir(cache_dir: Path) -> None:
    list_children_cache.set_cache_dir(cache_dir)


def reset_list_folder_children_cache(
    folder_id: Optional[str] = None, drive_id: str = "", page_size: Optional[int] = None
) -> None:
    list_children_cache.reset(folder_id, drive_id, page_size)


list_children_cache = ListFolderChildrenCache()
