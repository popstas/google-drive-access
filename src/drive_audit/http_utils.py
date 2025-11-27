"""Shared HTTP handler utilities."""

import json
import logging
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict

from .model import HttpConfig
from .translations import translate

logger = logging.getLogger(__name__)


class LocalizedError(Exception):
    def __init__(self, key: str, **context: Any) -> None:
        super().__init__(key)
        self.key = key
        self.context = context


class JsonRequestHandler(BaseHTTPRequestHandler):
    """Base handler with JSON helpers and token authentication."""

    http_config: HttpConfig
    language: str

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        logger.info("%s - %s", self.address_string(), format % args)

    def translate(self, key: str, **context: Any) -> str:
        return translate(self.language, key, **context)

    def send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        logger.info("%s answer: %s", self.path, json.dumps(payload, ensure_ascii=False))
        response = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def parse_json_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            raise LocalizedError("request_body_required")
        body = self.rfile.read(content_length)
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise LocalizedError("invalid_json", detail=exc.msg) from exc

    def authenticate(self) -> bool:
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self.send_json(
                200, {"answer": self.translate("missing_or_invalid_auth_header")}
            )
            return False

        token = auth_header.split(" ", 1)[1]
        if token != self.http_config.token:
            self.send_json(200, {"answer": self.translate("invalid_token")})
            return False
        return True
