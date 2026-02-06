"""HTTP handler for managing Google Drive access."""

import json
from typing import Any, Dict, List

from loguru import logger

from ..http_utils import JsonRequestHandler, LocalizedError
from ..model import DriveConfig, HttpConfig
from ..planfix_client import PlanfixClient
from ..translations import translate
from . import create_client_folder as create_client_folder_route
from . import set_client_folder_access as set_client_folder_access_route
from . import share_file as share_file_route


def create_handler(
    planfix_client: PlanfixClient,
    service,
    http_config: HttpConfig,
    drive_config: DriveConfig,
    role: str,
    share_file_config=None,
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
                set_client_folder_access_route.handle(
                    self,
                    payload,
                    planfix_client=planfix_client,
                    service=service,
                    drive_config=drive_config,
                    role=role,
                )
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
                create_client_folder_route.handle(
                    self,
                    payload,
                    planfix_client=planfix_client,
                    service=service,
                    drive_config=drive_config,
                    role=role,
                )
                return

            if self.path == "/share_file":
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
                share_file_route.handle(
                    self,
                    payload,
                    service=service,
                    drive_config=drive_config,
                    share_file_config=share_file_config,
                )
                return

            self.send_json(200, {"answer": translate(language, "not_found")})

    return AccessHandler
