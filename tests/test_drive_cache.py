import time
from pathlib import Path

from drive_audit.drive_cache import (
    DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT,
    ListFolderChildrenCache,
    reset_list_folder_children_cache,
    set_list_folder_children_cache_dir,
)


def test_cache_store_and_retrieve_in_memory(tmp_path):
    cache_dir = tmp_path / "cache"
    cache = ListFolderChildrenCache(cache_dir)

    cache.store_cached_children("drive", "folder", 100, [{"id": 1}], 3600)
    children = cache.get_cached_children("drive", "folder", 100, 3600)

    assert children == [{"id": 1}]
    children.append({"id": 2})
    assert cache.get_cached_children("drive", "folder", 100, 3600) == [{"id": 1}]


def test_cache_expires_entries(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache = ListFolderChildrenCache(cache_dir)

    cache.store_cached_children("", "folder", 50, [{"id": "child"}], 1)

    cached_at, cached_files = cache._cache[("", "folder", 50)]
    cache._cache[("", "folder", 50)] = (cached_at - 10, cached_files)

    assert cache.get_cached_children("", "folder", 50, 5) is None


def test_cache_persists_to_disk(tmp_path):
    cache_dir = tmp_path / "cache"
    cache = ListFolderChildrenCache(cache_dir)
    cache.store_cached_children("", "folder", 100, [{"id": "child"}], 3600)

    second_cache = ListFolderChildrenCache(cache_dir)
    children = second_cache.get_cached_children("", "folder", 100, 3600)

    assert children == [{"id": "child"}]


def test_global_cache_helpers(tmp_path):
    cache_dir = tmp_path / "cache"
    set_list_folder_children_cache_dir(cache_dir)
    reset_list_folder_children_cache()

    from drive_audit import drive_cache

    drive_cache.list_children_cache.store_cached_children(
        "", "folder", 100, [{"id": "child"}], DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT
    )

    children = drive_cache.list_children_cache.get_cached_children(
        "", "folder", 100, DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT
    )

    assert children == [{"id": "child"}]

    reset_list_folder_children_cache("folder", "", 100)
    assert (
        drive_cache.list_children_cache.get_cached_children(
            "", "folder", 100, DEFAULT_LIST_FOLDER_CHILDREN_CACHE_TIMEOUT
        )
        is None
    )
