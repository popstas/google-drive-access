"""HTTP handler for managing Google Drive access."""

import ast
import json
import logging
import re
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, List, Union
from urllib.parse import parse_qs, urlparse

from .google_client import (
    add_user_permission,
    create_folder,
    ensure_public_subdir,
    find_child_folder,
    get_file_permissions,
)
from .model import DriveConfig, HttpConfig
from .planfix_client import PlanfixClient
from .translations import translate

logger = logging.getLogger(__name__)


class LocalizedError(Exception):
    def __init__(self, key: str, **context: Any) -> None:
        super().__init__(key)
        self.key = key
        self.context = context


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
                "Collected google account %s for assignee %s",
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


def create_handler(
    planfix_client: PlanfixClient,
    service,
    http_config: HttpConfig,
    drive_config: DriveConfig,
    role: str,
):
    language = http_config.lang

    class AccessHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            logger.info("%s - %s", self.address_string(), format % args)

        def _log_request(self, payload: Dict[str, Any]) -> None:
            logger.info(
                "%s request: %s", self.path, json.dumps(payload, ensure_ascii=False)
            )

        def _translate(self, key: str, **context: Any) -> str:
            return translate(language, key, **context)

        def _format_accounts(self, accounts: List[str]) -> str:
            return ", ".join(accounts) if accounts else self._translate("none")

        def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
            logger.info(
                "%s answer: %s", self.path, json.dumps(payload, ensure_ascii=False)
            )
            response = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def _authenticate(self) -> bool:
            auth_header = self.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                self._send_json(
                    200, {"answer": self._translate("missing_or_invalid_auth_header")}
                )
                return False

            token = auth_header.split(" ", 1)[1]
            if token != http_config.token:
                self._send_json(200, {"answer": self._translate("invalid_token")})
                return False
            return True

        def _parse_body(self) -> Dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length == 0:
                raise LocalizedError("request_body_required")
            body = self.rfile.read(content_length)
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                raise LocalizedError("invalid_json", detail=exc.msg) from exc

        def _grant_access(
            self, task_id: int, initial_assignee_ids: List[str], folder_id: str
        ) -> Dict[str, List[str]]:
            if drive_config.public_subdir:
                ensure_public_subdir(
                    service,
                    folder_id,
                    drive_config.public_subdir,
                    drive_config.drive_id,
                )

            tasks = planfix_client.get_child_tasks(task_id)
            assignee_ids = PlanfixClient.collect_assignee_ids(
                tasks, initial_assignee_ids
            )
            google_accounts = collect_google_accounts(
                planfix_client, sorted(assignee_ids)
            )
            existing_accounts = collect_existing_user_accounts(service, folder_id)
            existing_accounts_set = set(existing_accounts)

            new_accounts = [
                account
                for account in google_accounts
                if account not in existing_accounts_set
            ]

            if new_accounts:
                set_permissions(service, folder_id, new_accounts, role)

            return {
                "granted_accounts": new_accounts,
                "existing_accounts": [
                    account
                    for account in google_accounts
                    if account in existing_accounts_set
                ],
            }

        def _handle_set_client_folder_access(self, payload: Dict[str, Any]) -> None:
            required_fields = ["contact_id", "folder_url"]
            missing_fields = [
                field for field in required_fields if field not in payload
            ]
            if missing_fields:
                self._send_json(
                    200,
                    {
                        "answer": self._translate(
                            "missing_fields", fields=", ".join(missing_fields)
                        )
                    },
                )
                return

            try:
                contact_id = int(payload["contact_id"])
                folder_id = extract_folder_id(str(payload["folder_url"]))

                has_task_id = "task_id" in payload
                has_assignee_id = "assignee_id" in payload

                if has_task_id and has_assignee_id:
                    task_id = int(payload["task_id"])
                    initial_assignee_ids = normalize_assignee_ids(
                        parse_assignee_ids(payload["assignee_id"])
                    )
                elif not has_task_id and not has_assignee_id:
                    client_task = planfix_client.get_client_task(contact_id)
                    if not client_task.get("found"):
                        self._send_json(
                            200, {"answer": self._translate("client_task_not_found")}
                        )
                        return

                    task_id = int(client_task.get("taskId"))
                    assignees = client_task.get("assignees", {}).get("users", [])
                    initial_assignee_ids = normalize_assignee_ids(assignees)
                else:
                    self._send_json(
                        200,
                        {"answer": self._translate("task_and_assignee_together")},
                    )
                    return

                access_report = self._grant_access(
                    task_id, initial_assignee_ids, folder_id
                )
            except LocalizedError as exc:
                self._send_json(
                    200, {"answer": self._translate(exc.key, **exc.context)}
                )
                return
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Failed to process request: %s", exc)
                self._send_json(
                    200, {"answer": self._translate("internal_server_error")}
                )
                return

            granted_accounts = access_report["granted_accounts"]
            existing_accounts = access_report["existing_accounts"]
            answer = self._translate(
                "granted_existing",
                granted=self._format_accounts(granted_accounts),
                existing=self._format_accounts(existing_accounts),
            )
            self._send_json(
                200,
                {
                    "answer": answer,
                    "granted_accounts": granted_accounts,
                    "existing_accounts": existing_accounts,
                },
            )

        def _handle_create_client_folder(self, payload: Dict[str, Any]) -> None:
            required_fields = ["contact_id", "folder_name"]
            missing_fields = [
                field for field in required_fields if field not in payload
            ]
            if missing_fields:
                self._send_json(
                    200,
                    {
                        "answer": self._translate(
                            "missing_fields", fields=", ".join(missing_fields)
                        )
                    },
                )
                return

            try:
                contact_id = int(payload["contact_id"])
                folder_name = str(payload["folder_name"]).strip()
                if not folder_name:
                    raise LocalizedError("folder_name_empty")

                client_task = planfix_client.get_client_task(contact_id)
                if not client_task.get("found"):
                    self._send_json(
                        200, {"answer": self._translate("client_task_not_found")}
                    )
                    return

                task_id = int(client_task.get("taskId"))
                assignees = client_task.get("assignees", {}).get("users", [])
                initial_assignee_ids = normalize_assignee_ids(assignees)

                existing_folder = find_child_folder(
                    service,
                    drive_config.root_folder_id,
                    folder_name,
                    drive_config.drive_id,
                )
                if existing_folder:
                    folder_url = f"https://drive.google.com/drive/folders/{existing_folder['id']}"
                    self._send_json(
                        200,
                        {
                            "answer": self._translate(
                                "client_folder_exists", folder_url=folder_url
                            )
                        },
                    )
                    return

                folder = create_folder(
                    service,
                    drive_config.root_folder_id,
                    folder_name,
                    drive_config.drive_id,
                )
                access_report = self._grant_access(
                    task_id, initial_assignee_ids, folder["id"]
                )
            except LocalizedError as exc:
                self._send_json(
                    200, {"answer": self._translate(exc.key, **exc.context)}
                )
                return
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Failed to process request: %s", exc)
                self._send_json(
                    200, {"answer": self._translate("internal_server_error")}
                )
                return

            granted_accounts = access_report["granted_accounts"]
            existing_accounts = access_report["existing_accounts"]
            answer = self._translate(
                "granted_existing",
                granted=self._format_accounts(granted_accounts),
                existing=self._format_accounts(existing_accounts),
            )
            folder_url = f"https://drive.google.com/drive/folders/{folder['id']}"
            self._send_json(
                200,
                {
                    "answer": self._translate(
                        "folder_created",
                        folder_name=folder_name,
                        details=answer,
                        folder_url=folder_url,
                    ),
                    "folder_id": folder["id"],
                    "folder_url": folder_url,
                    "granted_accounts": granted_accounts,
                    "existing_accounts": existing_accounts,
                },
            )

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/set_client_folder_access":
                if not self._authenticate():
                    return

                try:
                    payload = self._parse_body()
                except LocalizedError as exc:
                    self._send_json(
                        200, {"answer": self._translate(exc.key, **exc.context)}
                    )
                    return

                self._log_request(payload)
                self._handle_set_client_folder_access(payload)
                return

            if self.path == "/create_client_folder":
                if not self._authenticate():
                    return

                try:
                    payload = self._parse_body()
                except LocalizedError as exc:
                    self._send_json(
                        200, {"answer": self._translate(exc.key, **exc.context)}
                    )
                    return

                self._log_request(payload)
                self._handle_create_client_folder(payload)
                return

            self._send_json(200, {"answer": self._translate("not_found")})

    return AccessHandler
