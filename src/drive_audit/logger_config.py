"""Loguru logger configuration module."""

import sys
from pathlib import Path
from typing import Optional

from loguru import logger


def configure_logger(
    log_level: str = "INFO",
    log_file_path: Optional[Path] = None,
    enable_file_logging: bool = True,
    enable_console_logging: bool = True,
    rotation_size: Optional[str] = None,
    rotation_time: str = "1 day",
    retention: str = "30 days",
    compression: str = "zip",
) -> None:
    """
    Configure Loguru logger with file rotation and compression.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file_path: Path to log file. Defaults to data/app.log
        enable_file_logging: Whether to enable file logging
        enable_console_logging: Whether to enable console logging
        rotation_size: Size at which log file rotates (e.g., "10 MB", "1 GB").
                      None to disable size-based rotation (default on Windows due to seek issues)
        rotation_time: Time-based rotation (e.g., "1 day", "1 week"). Defaults to "1 day"
        retention: How long to keep old log files (e.g., "30 days", "1 week")
        compression: Compression format for old logs ("zip", "gz", or None)
    """
    # Remove default handler
    logger.remove()

    # Console handler with color and simple format
    if enable_console_logging:
        logger.add(
            sys.stderr,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level} </level> | <level>{message}</level>",
            level=log_level,
            colorize=True,
        )

    # File handler with rotation and compression
    if enable_file_logging:
        if log_file_path is None:
            log_file_path = Path("data") / "app.log"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Use time-based rotation on Windows to avoid seek() issues with size-based rotation
        # On other platforms, use size-based rotation if specified
        rotation = (
            rotation_time
            if sys.platform == "win32" or rotation_size is None
            else rotation_size
        )

        logger.add(
            str(log_file_path),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {message}",
            level=log_level,
            rotation=rotation,
            retention=retention,
            compression=compression,
            encoding="utf-8",
            backtrace=True,
            diagnose=True,
        )
