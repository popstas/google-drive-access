"""Service-level helpers for Drive and Planfix orchestration."""

import ast
import json
import re
from typing import Any, Dict, List, Tuple, Union
from urllib.parse import parse_qs, urlparse

from loguru import logger

from .google_client import (
    add_user_permission,
    create_folder,
    ensure_public_subdir,
    find_child_folder,
    get_file_permissions,
)
from .http_utils import LocalizedError
from .model import DriveConfig
from .planfix_client import PlanfixClient


def extract_file_id(document_url: str) -> str:
    parsed = urlparse(document_url)
    query_params = parse_qs(parsed.query)
    if "id" in query_params and query_params["id"]:
        return query_params["id"][0]

    match = re.search(
        r"/(?:document|spreadsheets|presentation|file|folders)/d?/?([A-Za-z0-9_-]+)",
        parsed.path,
    )
    if match:
        return match.group(1)

    raise LocalizedError("unable_extract_file_id")


def extract_folder_id(folder_url: str) -> str:
    parsed = urlparse(folder_url)
    query_params = parse_qs(parsed.query)
    if "id" in query_params and query_params["id"]:
        return query_params["id"][0]

    match = re.search(r"/folders/([A-Za-z0-9_-]+)", parsed.path)
    if match:
        return match.group(1)

    raise LocalizedError("unable_extract_folder_id")


def parse_assignee_ids(assignee_id: Any) -> List[str]:
    """
    Parse assignee_id which can be:
    - A single value (string or number)
    - A Python-style array string like "['7', '1']"
    - A JSON array string like '["7", "1"]'
    - An actual JSON array
    """
    if isinstance(assignee_id, list):
        return [str(item) for item in assignee_id]

    if isinstance(assignee_id, (int, float)):
        return [str(assignee_id)]

    assignee_id_str = str(assignee_id).strip()

    if assignee_id_str.startswith("[") or (
        assignee_id_str.startswith("'") and "[" in assignee_id_str
    ):
        try:
            parsed = ast.literal_eval(assignee_id_str)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (ValueError, SyntaxError):
            pass

        try:
            parsed = json.loads(assignee_id_str)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass

    return [assignee_id_str]


def normalize_assignee_ids(assignee_ids: List[Union[str, Dict[str, Any]]]) -> List[str]:
    normalized_ids: List[str] = []
    for assignee_id in assignee_ids:
        if isinstance(assignee_id, dict):
            assignee_str = str(assignee_id.get("id", "")).strip()
        else:
            assignee_str = str(assignee_id).strip()

        if not assignee_str:
            continue

        if assignee_str.startswith("user:"):
            assignee_str = assignee_str.split(":", 1)[1]
        normalized_ids.append(assignee_str)
    return normalized_ids


def collect_google_accounts(
    planfix_client: PlanfixClient, assignee_ids: List[str]
) -> List[str]:
    google_accounts: List[str] = []
    seen_accounts = set()
    for assignee_id in assignee_ids:
        manager = planfix_client.get_manager(assignee_id)
        google_account = manager.get("google_account")
        if google_account and google_account not in seen_accounts:
            seen_accounts.add(google_account)
            google_accounts.append(google_account)
            logger.debug(
                "Collected google account {} for assignee {}",
                google_account,
                assignee_id,
            )
    return google_accounts


def set_permissions(
    service, folder_id: str, google_accounts: List[str], role: str
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for account in google_accounts:
        permission = add_user_permission(service, folder_id, account, role)
        results.append(
            {
                "email": account,
                "permission_id": permission.get("id"),
                "role": role,
            }
        )
    return results


def collect_existing_user_accounts(service, folder_id: str) -> List[str]:
    permissions = get_file_permissions(service, folder_id)
    return [
        permission["emailAddress"]
        for permission in permissions
        if permission.get("type") == "user" and permission.get("emailAddress")
    ]


def grant_access(
    planfix_client: PlanfixClient,
    drive_service,
    drive_config: DriveConfig,
    role: str,
    task_id: int,
    initial_assignee_ids: List[str],
    folder_id: str,
    email: str = None,
) -> Dict[str, List[str]]:
    if drive_config.public_subdir:
        ensure_public_subdir(
            drive_service,
            folder_id,
            drive_config.public_subdir,
            drive_config.drive_id,
        )

    if email:
        google_accounts = [email]
    else:
        tasks = planfix_client.get_child_tasks(task_id)
        assignee_ids = PlanfixClient.collect_assignee_ids(tasks, initial_assignee_ids)
        google_accounts = collect_google_accounts(planfix_client, sorted(assignee_ids))
    existing_accounts = collect_existing_user_accounts(drive_service, folder_id)
    existing_accounts_set = set(existing_accounts)

    new_accounts = [
        account for account in google_accounts if account not in existing_accounts_set
    ]

    if new_accounts:
        set_permissions(drive_service, folder_id, new_accounts, role)

    return {
        "granted_accounts": new_accounts,
        "existing_accounts": [
            account for account in google_accounts if account in existing_accounts_set
        ],
    }


def get_task_and_assignees(
    planfix_client: PlanfixClient, contact_id: int
) -> Tuple[int, List[str]]:
    client_task = planfix_client.get_client_task(contact_id)
    if not client_task.get("found"):
        raise LocalizedError("client_task_not_found")

    task_id = int(client_task.get("taskId"))
    assignees = client_task.get("assignees", {}).get("users", [])
    initial_assignee_ids = normalize_assignee_ids(assignees)
    return task_id, initial_assignee_ids


def create_client_folder(drive_service, drive_config: DriveConfig, folder_name: str):
    folder_name = folder_name.strip()
    if not folder_name:
        raise LocalizedError("folder_name_empty")

    existing_folder = find_child_folder(
        drive_service,
        drive_config.root_folder_id,
        folder_name,
        drive_config.drive_id,
    )
    if existing_folder:
        return existing_folder, False

    folder = create_folder(
        drive_service,
        drive_config.root_folder_id,
        folder_name,
        drive_config.drive_id,
    )
    return folder, True
