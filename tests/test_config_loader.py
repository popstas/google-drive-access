import pytest

from drive_audit.config_loader import (
    build_http_config,
    build_moderate_delete_config,
    build_planfix_config,
    build_share_file_config,
    load_config,
)


@pytest.fixture
def sample_config_data():
    return {
        "lang": "ru",
        "planfix": {
            "getChildTasks": {"url": "child_url", "token": "child_token"},
            "getManager": {"url": "manager_url", "token": "manager_token"},
            "getClientTask": {"url": "client_url", "token": "client_token"},
            "updateContact": {"url": "update_url", "token": "update_token"},
            "role": "writer",
        },
        "http": {"port": 1234, "token": "secret"},
    }


def test_build_planfix_config(sample_config_data):
    planfix_config = build_planfix_config(sample_config_data)

    assert planfix_config.role == "writer"
    assert planfix_config.get_child_tasks.url == "child_url"
    assert planfix_config.get_child_tasks.token == "child_token"
    assert planfix_config.get_manager.url == "manager_url"
    assert planfix_config.get_manager.token == "manager_token"
    assert planfix_config.get_client_task.url == "client_url"
    assert planfix_config.get_client_task.token == "client_token"
    assert planfix_config.update_contact.url == "update_url"
    assert planfix_config.update_contact.token == "update_token"
    assert planfix_config.timeout == 120  # Default timeout


def test_build_http_config_respects_language(sample_config_data):
    http_config = build_http_config(sample_config_data)

    assert http_config.lang == "ru"
    assert http_config.port == 1234
    assert http_config.token == "secret"


def test_build_http_config_defaults_to_english_for_unknown_lang(sample_config_data):
    sample_config_data["lang"] = "de"

    http_config = build_http_config(sample_config_data)

    assert http_config.lang == "en"


def test_share_file_config_keeps_client_folder_private_by_default(sample_config_data):
    share_file_config = build_share_file_config(sample_config_data)

    assert share_file_config.public_client_folder is False
    assert share_file_config.role == "commenter"
    assert share_file_config.days == 90


def test_share_file_config_reads_public_client_folder(sample_config_data):
    sample_config_data["share_file"] = {
        "days": 0,
        "role": "commenter",
        "public_client_folder": True,
    }

    share_file_config = build_share_file_config(sample_config_data)

    assert share_file_config.public_client_folder is True


def test_missing_planfix_section_raises_value_error(sample_config_data):
    sample_config_data.pop("planfix")

    with pytest.raises(ValueError):
        build_planfix_config(sample_config_data)


def test_missing_http_section_raises_value_error(sample_config_data):
    sample_config_data.pop("http")

    with pytest.raises(ValueError):
        build_http_config(sample_config_data)


def test_build_moderate_delete_config_defaults():
    md_config = build_moderate_delete_config({})

    assert md_config.sheet_id == ""
    assert md_config.name_marker == "+delete"
    assert md_config.scan_roots == []
    assert md_config.scan_interval_seconds == 300
    assert md_config.max_per_run == 200
    assert md_config.report_csv == "deletions-report.csv"
    assert md_config.use_activity_api is False
    assert md_config.allowed_renamer_domains == []
    assert md_config.allow_folder_delete is False


def test_build_moderate_delete_config_defaults_with_empty_section():
    md_config = build_moderate_delete_config({"commands": {"moderate_delete": {}}})

    assert md_config.sheet_id == ""
    assert md_config.max_per_run == 200


def test_build_moderate_delete_config_overrides():
    config_data = {
        "commands": {
            "moderate_delete": {
                "sheet_id": "sheet123",
                "name_marker": "+remove",
                "scan_roots": ["folder1", "folder2"],
                "scan_interval_seconds": 60,
                "max_per_run": 50,
                "report_csv": "custom-report.csv",
                "use_activity_api": True,
                "allowed_renamer_domains": ["trusted.example", "example.com"],
                "allow_folder_delete": True,
            }
        }
    }

    md_config = build_moderate_delete_config(config_data)

    assert md_config.sheet_id == "sheet123"
    assert md_config.name_marker == "+remove"
    assert md_config.scan_roots == ["folder1", "folder2"]
    assert md_config.scan_interval_seconds == 60
    assert md_config.max_per_run == 50
    assert md_config.report_csv == "custom-report.csv"
    assert md_config.use_activity_api is True
    assert md_config.allowed_renamer_domains == [
        "trusted.example",
        "example.com",
    ]
    assert md_config.allow_folder_delete is True


def test_load_config_reads_yaml(tmp_path):
    config_content = """
lang: en
http:
  port: 8080
  token: secret
planfix:
  getChildTasks:
    url: child
    token: a
  getManager:
    url: manager
    token: b
  getClientTask:
    url: client
    token: c
  updateContact:
    url: update
    token: d
  role: reader
  timeout: 180
"""
    config_path = tmp_path / "config.yml"
    config_path.write_text(config_content)

    config = load_config(str(config_path))

    assert config["lang"] == "en"
    assert config["http"]["port"] == 8080
    planfix_config = build_planfix_config(config)
    assert planfix_config.timeout == 180
