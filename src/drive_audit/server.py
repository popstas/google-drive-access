import argparse
import ast
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

import yaml

from .google_client import add_user_permission, ensure_public_subdir, get_service
from .model import DriveConfig, HttpConfig, PlanfixConfig, PlanfixEndpointConfig
from .planfix_client import PlanfixClient

logger = logging.getLogger(__name__)


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
        role=planfix_section["role"],
    )


def build_http_config(config_data: Dict[str, Any]) -> HttpConfig:
    http_section = config_data.get("http")
    if not http_section:
        raise ValueError("http configuration section is missing")
    return HttpConfig(port=int(http_section["port"]), token=str(http_section["token"]))


def build_drive_config(config_data: Dict[str, Any]) -> DriveConfig:
    drive_section = config_data["drive"]
    google_section = config_data["google"]
    scan_section = config_data.get("scan", {})
    output_section = config_data.get("output", {})

    root_folder_id = drive_section.get("root_folder_id", drive_section["id"])
    if root_folder_id == "ROOT_FOLDER_ID":
        root_folder_id = drive_section["id"]

    return DriveConfig(
        credentials_file=google_section["credentials_file"],
        delegated_user=google_section.get("delegated_user"),
        drive_id=drive_section["id"],
        root_folder_id=root_folder_id,
        root_folder_name=drive_section["root_folder_name"],
        include_trashed=scan_section.get("include_trashed", False),
        include_shortcuts=scan_section.get("include_shortcuts", True),
        max_depth=scan_section.get("max_depth"),
        limit=scan_section.get("limit"),
        public_subdir=scan_section.get("public_subdir"),
        output_dir=output_section.get("dir", "./data"),
        yaml_file=output_section.get("yaml_file", "drive_audit.yml"),
        files_csv=output_section.get("files_csv", "files.csv"),
        permissions_csv=output_section.get("permissions_csv", "permissions.csv"),
    )


def extract_folder_id(folder_url: str) -> str:
    parsed = urlparse(folder_url)
    query_params = parse_qs(parsed.query)
    if "id" in query_params and query_params["id"]:
        return query_params["id"][0]

    match = re.search(r"/folders/([A-Za-z0-9_-]+)", parsed.path)
    if match:
        return match.group(1)

    raise ValueError("Unable to extract folder_id from folder_url")


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

    # Try to parse as Python literal (handles "['7', '1']")
    if assignee_id_str.startswith("[") or (assignee_id_str.startswith("'") and "[" in assignee_id_str):
        try:
            # First try Python literal eval (handles "['7', '1']")
            parsed = ast.literal_eval(assignee_id_str)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (ValueError, SyntaxError):
            pass

        # Try JSON parsing (handles '["7", "1"]')
        try:
            parsed = json.loads(assignee_id_str)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass

    # Single value
    return [assignee_id_str]


def collect_google_accounts(planfix_client: PlanfixClient, assignee_ids: List[str]) -> List[str]:
    google_accounts: List[str] = []
    seen_accounts = set()
    for assignee_id in assignee_ids:
        manager = planfix_client.get_manager(assignee_id)
        google_account = manager.get("google_account")
        if google_account and google_account not in seen_accounts:
            seen_accounts.add(google_account)
            google_accounts.append(google_account)
            logger.debug("Collected google account %s for assignee %s", google_account, assignee_id)
    return google_accounts


def set_permissions(service, folder_id: str, google_accounts: List[str], role: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for account in google_accounts:
        permission = add_user_permission(service, folder_id, account, role)
        results.append({
            "email": account,
            "permission_id": permission.get("id"),
            "role": role,
        })
    return results


def create_handler(planfix_client: PlanfixClient, service, http_config: HttpConfig, drive_config: DriveConfig, role: str):
    class AccessHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            logger.info("%s - %s", self.address_string(), format % args)

        def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
            response = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def _authenticate(self) -> bool:
            auth_header = self.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                self._send_json(200, {"answer": "Missing or invalid Authorization header"})
                return False

            token = auth_header.split(" ", 1)[1]
            if token != http_config.token:
                self._send_json(200, {"answer": "Invalid token"})
                return False
            return True

        def _parse_body(self) -> Dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length == 0:
                raise ValueError("Request body is required")
            body = self.rfile.read(content_length)
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON: {exc.msg}") from exc

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/set_client_folder_access":
                self._send_json(200, {"answer": "Not found"})
                return

            if not self._authenticate():
                return

            try:
                payload = self._parse_body()
            except ValueError as exc:
                self._send_json(200, {"answer": str(exc)})
                return

            required_fields = ["contact_id", "folder_url", "task_id", "assignee_id"]
            missing_fields = [field for field in required_fields if field not in payload]
            if missing_fields:
                self._send_json(200, {"answer": f"Missing fields: {', '.join(missing_fields)}"})
                return

            try:
                task_id = int(payload["task_id"])
                initial_assignee_ids = parse_assignee_ids(payload["assignee_id"])
                folder_id = extract_folder_id(str(payload["folder_url"]))

                if drive_config.public_subdir:
                    ensure_public_subdir(service, folder_id, drive_config.public_subdir, drive_config.drive_id)

                tasks = planfix_client.get_child_tasks(task_id)
                assignee_ids = PlanfixClient.collect_assignee_ids(tasks, initial_assignee_ids)
                google_accounts = collect_google_accounts(planfix_client, sorted(assignee_ids))
                permission_results = set_permissions(service, folder_id, google_accounts, role)
            except ValueError as exc:
                self._send_json(200, {"answer": str(exc)})
                return
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Failed to process request: %s", exc)
                self._send_json(200, {"answer": "Internal server error"})
                return

            self._send_json(
                200,
                {
                    "answer": f"Access granted for {', '.join(google_accounts)}"
                }
            )
            

    return AccessHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP server for managing Google Drive access")
    parser.add_argument("--config", default="data/config.yml", help="Path to configuration file")
    args = parser.parse_args()

    config_data = load_config(args.config)
    log_level_name = str(config_data.get("logLevel", "INFO")).upper()
    logging.basicConfig(level=log_level_name, format="%(asctime)s - %(levelname)s - %(message)s")

    planfix_config = build_planfix_config(config_data)
    http_config = build_http_config(config_data)
    drive_config = build_drive_config(config_data)

    logger.info("Initializing Google Drive service")
    service = get_service(drive_config)
    planfix_client = PlanfixClient(planfix_config)

    handler = create_handler(planfix_client, service, http_config, drive_config, planfix_config.role)
    server = HTTPServer(("", http_config.port), handler)
    logger.info("Starting HTTP server on port %s", http_config.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    finally:
        server.server_close()
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
