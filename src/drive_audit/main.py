import argparse
import yaml
import logging
import os
import sys
from .model import DriveConfig
from .google_client import get_service, list_files
from .scanner import build_file_tree
from .export_yaml import save_yaml
from .export_csv import save_files_csv, save_permissions_csv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def load_config(config_path: str) -> dict:
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def main():
    parser = argparse.ArgumentParser(description="Google Drive Audit CLI")
    parser.add_argument('--config', default='data/config.yml', help='Path to configuration file')
    parser.add_argument('--drive-id', help='Shared Drive ID')
    parser.add_argument('--root-folder-id', help='Root folder ID')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    logger.info(f"Loading configuration from {args.config}")
    try:
        config_data = load_config(args.config)
    except FileNotFoundError:
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)
        
    # Override config with CLI args
    if args.drive_id:
        config_data['drive']['id'] = args.drive_id
    if args.root_folder_id:
        config_data['drive']['root_folder_id'] = args.root_folder_id
        
    # Handle placeholder root_folder_id
    if config_data['drive']['root_folder_id'] == 'ROOT_FOLDER_ID':
        logger.info(f"root_folder_id is placeholder, defaulting to drive_id: {config_data['drive']['id']}")
        config_data['drive']['root_folder_id'] = config_data['drive']['id']
        
    # Create DriveConfig object
    config = DriveConfig(
        credentials_file=config_data['google']['credentials_file'],
        delegated_user=config_data['google'].get('delegated_user'),
        drive_id=config_data['drive']['id'],
        root_folder_id=config_data['drive']['root_folder_id'],
        root_folder_name=config_data['drive']['root_folder_name'],
        include_trashed=config_data['scan']['include_trashed'],
        include_shortcuts=config_data['scan']['include_shortcuts'],
        max_depth=config_data['scan'].get('max_depth'),
        public_folder_name=config_data['scan']['public_folder_name'],
        output_dir=config_data['output']['dir'],
        yaml_file=config_data['output']['yaml_file'],
        files_csv=config_data['output']['files_csv'],
        permissions_csv=config_data['output']['permissions_csv']
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
        raw_files = list(list_files(service, config.drive_id))
        logger.info(f"Found {len(raw_files)} files/folders.")
        
        # 2. Build Tree & Process
        logger.info("Processing files and building tree...")
        processed_files = build_file_tree(raw_files, config)
        logger.info(f"Processed {len(processed_files)} files after filtering.")
        
        # 3. Export
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
