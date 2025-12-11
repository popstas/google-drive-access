"""HTTP handler for managing Google Drive access."""

import json
from typing import Any, Dict, List

from loguru import logger

from .access_service import (
    create_client_folder,
    extract_folder_id,
    get_task_and_assignees,
    grant_access,
    normalize_assignee_ids,
    parse_assignee_ids,
)
from .http_utils import JsonRequestHandler, LocalizedError
from .model import DriveConfig, HttpConfig
from .planfix_client import PlanfixClient
from .translations import translate


def create_handler(
    planfix_client: PlanfixClient,
    service,
    http_config: HttpConfig,
    drive_config: DriveConfig,
    role: str,
):
    handler_http_config = http_config
    handler_language = http_config.lang

    class AccessHandler(JsonRequestHandler):
        http_config = handler_http_config
        language = handler_language

        def _log_request(self, payload: Dict[str, Any]) -> None:
            logger.info(
                "{} request: {}", self.path, json.dumps(payload, ensure_ascii=False)
            )

        def _format_accounts(self, accounts: List[str]) -> str:
            return ", ".join(accounts) if accounts else self.translate("none")

        def _handle_set_client_folder_access(self, payload: Dict[str, Any]) -> None:
            required_fields = ["contact_id", "folder_url"]
            missing_fields = [
                field for field in required_fields if field not in payload
            ]
            if missing_fields:
                self.send_json(
                    200,
                    {
                        "answer": self.translate(
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
                    task_id, initial_assignee_ids = get_task_and_assignees(
                        planfix_client, contact_id
                    )
                else:
                    self.send_json(
                        200,
                        {"answer": self.translate("task_and_assignee_together")},
                    )
                    return

                access_report = grant_access(
                    planfix_client,
                    service,
                    drive_config,
                    role,
                    task_id,
                    initial_assignee_ids,
                    folder_id,
                )
            except LocalizedError as exc:
                self.send_json(200, {"answer": self.translate(exc.key, **exc.context)})
                return
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Failed to process request: {}", exc)
                self.send_json(200, {"answer": self.translate("internal_server_error")})
                return

            granted_accounts = access_report["granted_accounts"]
            existing_accounts = access_report["existing_accounts"]
            answer = self.translate(
                "granted_existing",
                granted=self._format_accounts(granted_accounts),
                existing=self._format_accounts(existing_accounts),
            )
            self.send_json(
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
                self.send_json(
                    200,
                    {
                        "answer": self.translate(
                            "missing_fields", fields=", ".join(missing_fields)
                        )
                    },
                )
                return

            try:
                contact_id = int(payload["contact_id"])
                folder_name = str(payload["folder_name"]).strip()
                folder_name_words = folder_name.split()
                name_warning = ""
                if len(folder_name_words) == 1:
                    name_warning = " \n" + self.translate("folder_name_single_word")
                task_id, initial_assignee_ids = get_task_and_assignees(
                    planfix_client, contact_id
                )
                folder, created = create_client_folder(
                    service, drive_config, folder_name
                )
                if not created:
                    folder_url = (
                        f"https://drive.google.com/drive/folders/{folder['id']}"
                    )
                    answer_text = (
                        self.translate("client_folder_exists", folder_url=folder_url)
                        + name_warning
                    )
                    self.send_json(
                        200,
                        {"answer": answer_text},
                    )
                    return

                access_report = grant_access(
                    planfix_client,
                    service,
                    drive_config,
                    role,
                    task_id,
                    initial_assignee_ids,
                    folder["id"],
                )
            except LocalizedError as exc:
                self.send_json(200, {"answer": self.translate(exc.key, **exc.context)})
                return
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Failed to process request: {}", exc)
                self.send_json(200, {"answer": self.translate("internal_server_error")})
                return

            granted_accounts = access_report["granted_accounts"]
            existing_accounts = access_report["existing_accounts"]
            answer = self.translate(
                "granted_existing",
                granted=self._format_accounts(granted_accounts),
                existing=self._format_accounts(existing_accounts),
            )
            folder_url = f"https://drive.google.com/drive/folders/{folder['id']}"
            answer_text = (
                self.translate(
                    "folder_created",
                    folder_name=folder_name,
                    details=answer,
                    folder_url=folder_url,
                )
                + name_warning
            )
            self.send_json(
                200,
                {
                    "answer": answer_text,
                    "folder_id": folder["id"],
                    "folder_url": folder_url,
                    "granted_accounts": granted_accounts,
                    "existing_accounts": existing_accounts,
                },
            )

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/set_client_folder_access":
                if not self.authenticate():
                    return

                try:
                    payload = self.parse_json_body()
                except LocalizedError as exc:
                    self.send_json(
                        200, {"answer": self.translate(exc.key, **exc.context)}
                    )
                    return

                self._log_request(payload)
                self._handle_set_client_folder_access(payload)
                return

            if self.path == "/create_client_folder":
                if not self.authenticate():
                    return

                try:
                    payload = self.parse_json_body()
                except LocalizedError as exc:
                    self.send_json(
                        200, {"answer": self.translate(exc.key, **exc.context)}
                    )
                    return

                self._log_request(payload)
                self._handle_create_client_folder(payload)
                return

            self.send_json(200, {"answer": translate(language, "not_found")})

    return AccessHandler
