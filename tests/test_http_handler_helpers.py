import pytest

from drive_audit.access_service import (
    extract_folder_id,
    normalize_assignee_ids,
    parse_assignee_ids,
)
from drive_audit.http_utils import LocalizedError


def test_extract_folder_id_supports_query_and_path():
    assert (
        extract_folder_id("https://drive.google.com/open?id=folder123") == "folder123"
    )
    assert (
        extract_folder_id("https://drive.google.com/drive/folders/folder456")
        == "folder456"
    )


def test_extract_folder_id_raises_when_missing():
    with pytest.raises(LocalizedError):
        extract_folder_id("https://drive.google.com/drive")


def test_parse_assignee_ids_handles_multiple_formats():
    assert parse_assignee_ids([1, "2"]) == ["1", "2"]
    assert parse_assignee_ids("['3', '4']") == ["3", "4"]
    assert parse_assignee_ids('["5", "6"]') == ["5", "6"]
    assert parse_assignee_ids(7) == ["7"]
    assert parse_assignee_ids("8") == ["8"]


def test_normalize_assignee_ids_removes_prefix_and_blanks():
    raw_ids = ["user:123", {"id": "456"}, "  ", "789"]

    assert normalize_assignee_ids(raw_ids) == ["123", "456", "789"]
