import argparse
import yaml
import logging
import os
import sys
from .model import DriveConfig
from .google_client import get_service, list_files, get_file_permissions
from .scanner import build_file_tree
from .export_yaml import save_yaml
from .export_csv import save_files_csv, save_permissions_csv

logger = logging.getLogger(__name__)

def load_config(config_path: str) -> dict:
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def get_log_level(level_name: str) -> int:
    """Convert string log level name to logging constant."""
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    return level_map.get(level_name.upper(), logging.INFO)

def main():
    parser = argparse.ArgumentParser(description="Google Drive Audit CLI")
    parser.add_argument('--config', default='data/config.yml', help='Path to configuration file')
    parser.add_argument('--drive-id', help='Shared Drive ID')
    parser.add_argument('--root-folder-id', help='Root folder ID')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Load config first to get logLevel
    logger.info(f"Loading configuration from {args.config}")
    try:
        config_data = load_config(args.config)
    except FileNotFoundError:
        # Use basic logging for error before config is loaded
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)
    
    # Configure logging from config
    log_level = get_log_level(config_data.get('logLevel', 'INFO'))
    if args.debug:
        log_level = logging.DEBUG
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True  # Override any existing configuration
    )
    logger.setLevel(log_level)
        
    drive_section = config_data.setdefault('drive', {})

    # Override config with CLI args, allow empty drive.id
    if args.drive_id:
        drive_section['id'] = args.drive_id
    drive_section['id'] = drive_section.get('id', '') or ''

    if args.root_folder_id:
        drive_section['root_folder_id'] = args.root_folder_id
    root_folder_id = drive_section.get('root_folder_id')

    # Handle placeholder or missing root_folder_id
    if root_folder_id == 'ROOT_FOLDER_ID':
        fallback_root = drive_section.get('id') or 'root'
        logger.info(f"root_folder_id is placeholder, defaulting to drive scope: {fallback_root}")
        drive_section['root_folder_id'] = fallback_root
    elif not root_folder_id:
        drive_section['root_folder_id'] = drive_section.get('id') or 'root'

    # Create DriveConfig object
    config = DriveConfig(
        credentials_file=config_data['google']['credentials_file'],
        delegated_user=config_data['google'].get('delegated_user'),
        drive_id=drive_section.get('id', ''),
        root_folder_id=drive_section['root_folder_id'],
        root_folder_name=drive_section['root_folder_name'],
        include_trashed=config_data['scan']['include_trashed'],
        include_shortcuts=config_data['scan']['include_shortcuts'],
        max_depth=config_data['scan'].get('max_depth'),
        limit=config_data['scan'].get('limit'),
        public_subdir=config_data['scan'].get('public_subdir'),
        output_dir=config_data['output']['dir'],
        yaml_file=config_data['output']['yaml_file'],
        files_csv=config_data['output']['files_csv'],
        permissions_csv=config_data['output']['permissions_csv'],
        list_folder_children_cache_timeout=int(
            config_data.get('cache_timeouts', {}).get('list_folder_children', 3600)
        ),
    )
    
    logger.info("Initializing Google Drive Service...")
    try:
        service = get_service(config)
    except Exception as e:
        logger.error(f"Failed to initialize service: {e}")
        sys.exit(1)
        
    logger.info(f"Scanning Drive ID: {config.drive_id}")
    
    try:
        # 1. List all files
        logger.info("Listing files...")
        raw_files = list(list_files(service, config.drive_id, limit=config.limit))
        if config.limit:
            logger.info(f"Found {len(raw_files)} files/folders (limited to {config.limit}).")
        else:
            logger.info(f"Found {len(raw_files)} files/folders.")
        
        # 2. Fetch permissions for each file
        logger.info("Fetching permissions for files...")
        files_with_perms = 0
        total_perms = 0
        for idx, file_data in enumerate(raw_files, 1):
            file_id = file_data.get('id')
            if file_id:
                permissions = get_file_permissions(service, file_id)
                file_data['permissions'] = permissions
                if permissions:
                    files_with_perms += 1
                    total_perms += len(permissions)
                if idx % 10 == 0:
                    logger.debug(f"Fetched permissions for {idx}/{len(raw_files)} files...")
        logger.info(f"Finished fetching permissions. {files_with_perms} files have permissions ({total_perms} total permissions).")
        
        # 3. Build Tree & Process
        logger.info("Processing files and building tree...")
        processed_files = build_file_tree(raw_files, config)
        logger.info(f"Processed {len(processed_files)} files after filtering.")
        
        # Debug: Check owners and permissions
        files_with_owners = sum(1 for f in processed_files if f.owners)
        files_with_permissions = sum(1 for f in processed_files if f.access and f.access.permissions)
        total_permissions = sum(len(f.access.permissions) if f.access else 0 for f in processed_files)
        logger.debug(f"Debug: {files_with_owners} files have owners, {files_with_permissions} files have permissions ({total_permissions} total).")
        
        # 4. Export
        if not os.path.exists(config.output_dir):
            os.makedirs(config.output_dir)
            
        yaml_path = os.path.join(config.output_dir, config.yaml_file)
        files_csv_path = os.path.join(config.output_dir, config.files_csv)
        perms_csv_path = os.path.join(config.output_dir, config.permissions_csv)
        
        logger.info(f"Exporting to YAML: {yaml_path}")
        save_yaml(processed_files, config, yaml_path)
        
        logger.info(f"Exporting Files CSV: {files_csv_path}")
        save_files_csv(processed_files, files_csv_path)
        
        logger.info(f"Exporting Permissions CSV: {perms_csv_path}")
        save_permissions_csv(processed_files, perms_csv_path)
        
        logger.info("Audit complete.")
        
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
