import argparse
import logging
from http.server import HTTPServer
from pathlib import Path

from .config_loader import build_http_config, build_planfix_config, load_config
from .google_client import get_service
from .http_handler import create_handler
from .model import DriveConfig
from .planfix_client import PlanfixClient

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HTTP server for managing Google Drive access"
    )
    parser.add_argument(
        "--config", default="data/config.yml", help="Path to configuration file"
    )
    args = parser.parse_args()

    config_data = load_config(args.config)
    log_level_name = str(config_data.get("logLevel", "INFO")).upper()
    log_file_path = Path("data") / "app.log"
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=log_level_name,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file_path, encoding="utf-8"),
        ],
        force=True,
    )

    planfix_config = build_planfix_config(config_data)
    http_config = build_http_config(config_data)
    drive_config = DriveConfig.from_dict(config_data)

    logger.info("Initializing Google Drive service")
    service = get_service(drive_config)
    planfix_client = PlanfixClient(planfix_config)

    handler = create_handler(
        planfix_client, service, http_config, drive_config, planfix_config.role
    )
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
