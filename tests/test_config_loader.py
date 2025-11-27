import pytest

from drive_audit.config_loader import (
    build_http_config,
    build_planfix_config,
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


def test_build_http_config_respects_language(sample_config_data):
    http_config = build_http_config(sample_config_data)

    assert http_config.lang == "ru"
    assert http_config.port == 1234
    assert http_config.token == "secret"


def test_build_http_config_defaults_to_english_for_unknown_lang(sample_config_data):
    sample_config_data["lang"] = "de"

    http_config = build_http_config(sample_config_data)

    assert http_config.lang == "en"


def test_missing_planfix_section_raises_value_error(sample_config_data):
    sample_config_data.pop("planfix")

    with pytest.raises(ValueError):
        build_planfix_config(sample_config_data)


def test_missing_http_section_raises_value_error(sample_config_data):
    sample_config_data.pop("http")

    with pytest.raises(ValueError):
        build_http_config(sample_config_data)


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
  role: reader
"""
    config_path = tmp_path / "config.yml"
    config_path.write_text(config_content)

    config = load_config(str(config_path))

    assert config["lang"] == "en"
    assert config["http"]["port"] == 8080
