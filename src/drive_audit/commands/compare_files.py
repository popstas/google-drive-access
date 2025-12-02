from pathlib import Path

from loguru import logger

from ..compare import compare_files_by_location


def run_compare_files(args, config_data, drive_config, service) -> None:  # noqa: ARG001
    compare_config = config_data.get("compare", {})
    ignore_public_subdir = compare_config.get("ignore_public_subdir", False)
    normalize_file_names = compare_config.get("normalize_file_names", False)
    ignore_format_differences = compare_config.get("ignore_format_differences", False)
    ignore_duplicate_suffixes = compare_config.get("ignore_duplicate_suffixes", False)
    ignore_folders = compare_config.get("ignore_folders", [])
    ignore_empty_folders = compare_config.get("ignore_empty_folders", False)
    public_subdir = drive_config.public_subdir

    logger.info(
        "Compare configuration: ignore_public_subdir={}, normalize_file_names={}, ignore_format_differences={}, ignore_duplicate_suffixes={}, ignore_folders={}, ignore_empty_folders={}",
        ignore_public_subdir,
        normalize_file_names,
        ignore_format_differences,
        ignore_duplicate_suffixes,
        ignore_folders,
        ignore_empty_folders,
    )

    result = compare_files_by_location(
        Path(args.csv_old),
        Path(args.csv_new),
        ignore_public_subdir=ignore_public_subdir,
        public_subdir=public_subdir,
        normalize_file_names=normalize_file_names,
        ignore_format_differences=ignore_format_differences,
        ignore_duplicate_suffixes=ignore_duplicate_suffixes,
        ignore_folders=ignore_folders if ignore_folders else None,
        ignore_empty_folders=ignore_empty_folders,
    )

    # Output statistics
    stats = result.get("stats", {})
    logger.info("=" * 60)
    logger.info("Comparison Statistics:")
    logger.info("  Total rows in old CSV: {}", stats.get("total_rows_old", 0))
    logger.info("  Total rows in new CSV: {}", stats.get("total_rows_new", 0))
    logger.info(
        "  Ignored public_subdir folders (old): {}",
        stats.get("ignored_public_subdirs_old", 0),
    )
    logger.info(
        "  Ignored public_subdir folders (new): {}",
        stats.get("ignored_public_subdirs_new", 0),
    )
    logger.info(
        "  Ignored folders and their children (old): {}",
        stats.get("ignored_folders_old", 0),
    )
    logger.info(
        "  Ignored folders and their children (new): {}",
        stats.get("ignored_folders_new", 0),
    )
    logger.info(
        "  Ignored empty folders (old): {}",
        stats.get("ignored_empty_folders_old", 0),
    )
    logger.info(
        "  Ignored empty folders (new): {}",
        stats.get("ignored_empty_folders_new", 0),
    )
    logger.info("  New-only rows: {}", stats.get("new_only_rows", 0))
    logger.info("  Old-only rows: {}", stats.get("old_only_rows", 0))
    logger.info("=" * 60)


__all__ = ["run_compare_files", "compare_files_by_location"]
