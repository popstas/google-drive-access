"""Configuration loading helpers."""

from typing import Any, Dict

import yaml

from .model import HttpConfig, PlanfixConfig, PlanfixEndpointConfig, ShareFileConfig
from .translations import TRANSLATIONS


def load_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def build_planfix_config(config_data: Dict[str, Any]) -> PlanfixConfig:
    planfix_section = config_data.get("planfix")
    if not planfix_section:
        raise ValueError("planfix configuration section is missing")
    return PlanfixConfig(
        get_child_tasks=PlanfixEndpointConfig(
            url=planfix_section["getChildTasks"]["url"],
            token=planfix_section["getChildTasks"]["token"],
        ),
        get_manager=PlanfixEndpointConfig(
            url=planfix_section["getManager"]["url"],
            token=planfix_section["getManager"]["token"],
        ),
        get_client_task=PlanfixEndpointConfig(
            url=planfix_section["getClientTask"]["url"],
            token=planfix_section["getClientTask"]["token"],
        ),
        update_contact=PlanfixEndpointConfig(
            url=planfix_section["updateContact"]["url"],
            token=planfix_section["updateContact"]["token"],
        ),
        role=planfix_section["role"],
        timeout=int(planfix_section.get("timeout", 120)),
    )


def build_share_file_config(config_data: Dict[str, Any]) -> ShareFileConfig:
    section = config_data.get("share_file", {})
    return ShareFileConfig(
        days=int(section.get("days", 90)),
        role=str(section.get("role", "commenter")),
    )


def build_http_config(config_data: Dict[str, Any]) -> HttpConfig:
    http_section = config_data.get("http")
    if not http_section:
        raise ValueError("http configuration section is missing")

    lang = str(config_data.get("lang", "en")).lower()
    if lang not in TRANSLATIONS:
        lang = "en"

    return HttpConfig(
        port=int(http_section["port"]), token=str(http_section["token"]), lang=lang
    )
