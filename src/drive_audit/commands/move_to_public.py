from typing import Any, Dict, List, Optional

from loguru import logger

from ..model import DriveConfig
from ..public_folder_ops import (
    collect_public_folder_matches,
    execute_public_folder_moves,
    validate_public_folder_move_inputs,
)


def move_files_to_public_folder(
    service,
    drive_config: DriveConfig,
    file_matches: Any,
    dry_run: bool,
    mime_type_matches: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    patterns, allowed_mime_types = validate_public_folder_move_inputs(
        drive_config, file_matches, mime_type_matches
    )

    matches = collect_public_folder_matches(
        service, drive_config, patterns, allowed_mime_types
    )

    return execute_public_folder_moves(service, matches, drive_config, dry_run)


def run_move_files_to_public_folder(args, config_data, drive_config, service) -> None:
    command_config = config_data.get("commands", {}).get(
        "move_files_to_public_folder", {}
    )
    configured_patterns = command_config.get("file_match")
    configured_mime_types = command_config.get("mime_type_match")
    if configured_mime_types is None:
        configured_mime_types = command_config.get("mimeType_match")

    if not configured_patterns:
        raise ValueError(
            "commands.move_files_to_public_folder.file_match must be configured"
        )

    if isinstance(configured_patterns, str):
        file_matches = [configured_patterns]
    elif isinstance(configured_patterns, list) and all(
        isinstance(pattern, str) for pattern in configured_patterns
    ):
        file_matches = configured_patterns
    else:
        raise ValueError(
            "commands.move_files_to_public_folder.file_match must be a string or list of strings"
        )

    if configured_mime_types is None:
        mime_type_matches = None
    elif isinstance(configured_mime_types, str):
        mime_type_matches = [configured_mime_types]
    elif isinstance(configured_mime_types, list) and all(
        isinstance(mime, str) for mime in configured_mime_types
    ):
        mime_type_matches = configured_mime_types
    else:
        raise ValueError(
            "commands.move_files_to_public_folder.mime_type_match must be a string or list of strings"
        )

    moved_files = move_files_to_public_folder(
        service, drive_config, file_matches, args.dry_run, mime_type_matches
    )
    logger.info("{} files processed", len(moved_files))
