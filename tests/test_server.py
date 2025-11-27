import sys
from types import SimpleNamespace

import pytest

from drive_audit import server


class DummyHTTPServer:
    def __init__(self, address, handler):
        self.address = address
        self.handler = handler
        self.closed = False

    def serve_forever(self):
        raise KeyboardInterrupt()

    def server_close(self):
        self.closed = True


def test_server_main(monkeypatch, tmp_path):
    config_data = {
        "logLevel": "INFO",
        "planfix": {},
    }

    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(tmp_path / "cfg.yml")])
    monkeypatch.setattr(server, "load_config", lambda path: config_data)
    monkeypatch.setattr(
        server,
        "build_planfix_config",
        lambda cfg: SimpleNamespace(role="writer"),
    )
    monkeypatch.setattr(
        server,
        "build_http_config",
        lambda cfg: SimpleNamespace(port=1234, token="t", lang="en"),
    )
    monkeypatch.setattr(
        server, "DriveConfig", SimpleNamespace(from_dict=lambda cfg: SimpleNamespace())
    )
    monkeypatch.setattr(server, "get_service", lambda cfg: SimpleNamespace())
    monkeypatch.setattr(server, "PlanfixClient", lambda cfg: SimpleNamespace())

    created_handlers = {}

    def fake_create_handler(planfix_client, service, http_cfg, drive_cfg, role):
        created_handlers["args"] = (planfix_client, service, http_cfg, drive_cfg, role)
        return lambda *a, **kw: None

    monkeypatch.setattr(server, "create_handler", fake_create_handler)
    monkeypatch.setattr(server, "HTTPServer", DummyHTTPServer)

    server.main()

    assert created_handlers["args"][4] == "writer"
    assert created_handlers["args"][2].port == 1234
