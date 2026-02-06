import argparse
from http.server import HTTPServer
from pathlib import Path

from loguru import logger

from .config_loader import (
    build_http_config,
    build_planfix_config,
    build_share_file_config,
    load_config,
)
from .google_client import get_service
from .http import create_handler
from .logger_config import configure_logger
from .model import DriveConfig
from .planfix_client import PlanfixClient


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
    configure_logger(
        log_level=log_level_name,
        log_file_path=log_file_path,
    )
    # Suppress file_cache warning from googleapiclient.discovery_cache
    logger.disable("googleapiclient.discovery_cache")

    planfix_config = build_planfix_config(config_data)
    http_config = build_http_config(config_data)
    drive_config = DriveConfig.from_dict(config_data)
    share_file_config = build_share_file_config(config_data)

    logger.info("Initializing Google Drive service")
    service = get_service(drive_config)
    planfix_client = PlanfixClient(planfix_config)

    handler = create_handler(
        planfix_client,
        service,
        http_config,
        drive_config,
        planfix_config.role,
        share_file_config=share_file_config,
    )
    server = HTTPServer(("", http_config.port), handler)
    logger.info("Starting HTTP server on port {}", http_config.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    finally:
        server.server_close()
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
