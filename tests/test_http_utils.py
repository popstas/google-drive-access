from io import BytesIO

import pytest

from drive_audit.http_utils import JsonRequestHandler, LocalizedError
from drive_audit.model import HttpConfig


class _StubHandler(JsonRequestHandler):
    http_config = HttpConfig(port=0, token="secret", lang="en")
    language = "en"


def _build_handler(body: bytes, headers: dict | None = None):
    handler = _StubHandler.__new__(_StubHandler)
    handler.headers = headers or {
        "Content-Length": str(len(body)),
        "Authorization": "Bearer secret",
    }
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    handler.path = "/test"
    status = {}
    headers_sent = []
    handler.send_response = lambda code: status.update(code=code)
    handler.send_header = lambda key, value: headers_sent.append((key, value))
    handler.end_headers = lambda: None
    return handler, status, headers_sent


def test_parse_json_body_returns_data():
    handler, _, _ = _build_handler(b'{"value": 1}')

    assert handler.parse_json_body() == {"value": 1}


def test_parse_json_body_validates_content_length():
    handler, _, _ = _build_handler(b"", headers={"Content-Length": "0"})

    with pytest.raises(LocalizedError):
        handler.parse_json_body()


def test_parse_json_body_rejects_invalid_json():
    handler, _, _ = _build_handler(b"not-json", headers={"Content-Length": "7"})

    with pytest.raises(LocalizedError):
        handler.parse_json_body()


def test_authenticate_rejects_invalid_token():
    handler, status, _ = _build_handler(
        b"{}", headers={"Content-Length": "2", "Authorization": "Bearer bad"}
    )

    assert handler.authenticate() is False
    assert status["code"] == 200
    handler.wfile.seek(0)
    assert b"Invalid token" in handler.wfile.read()


def test_authenticate_passes_with_valid_token():
    handler, status, _ = _build_handler(b"{}")

    assert handler.authenticate() is True
    assert status == {}
