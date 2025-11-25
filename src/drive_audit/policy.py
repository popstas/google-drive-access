from typing import List
from .model import FileInfo, DriveConfig, PolicyInfo

def check_policy(file_info: FileInfo, config: DriveConfig) -> PolicyInfo:
    """
    Analyzes file access against the policy.
    Determines if the file is public, if it's in a public folder, etc.
    """
    is_under_public_folder = False
    
    # Check if under public folder based on location
    # Location format: /ClientName/public/file.txt or /ClientName/public
    # We check if the configured public subdir is a segment in the path
    # Requirement: "True, если путь имеет вид "/<Client>/public/..." или папка public вторая в пути"

    parts = file_info.location.strip('/').split('/')
    public_segment = config.public_subdir or "public"
    if len(parts) >= 2:
        # Check if the second segment (index 1) is the public folder name
        # parts[0] is ClientName, parts[1] should be public folder
        if parts[1] == public_segment:
            is_under_public_folder = True
    
    is_public_anyone = False
    is_public_by_domain = False
    
    if file_info.access:
        if file_info.access.general_access == 'anyone':
            is_public_anyone = True
        if file_info.access.general_access == 'domain':
            is_public_by_domain = True
            
        # Also check individual permissions just in case, though general_access should cover it
        # But requirements say: "True, если есть permission type=anyone"
        for perm in file_info.access.permissions:
            if perm.type == 'anyone':
                is_public_anyone = True
            if perm.type == 'domain':
                is_public_by_domain = True

    public_outside_public_folder = False
    if is_public_anyone and not is_under_public_folder:
        public_outside_public_folder = True
        
    notes = []
    if public_outside_public_folder:
        notes.append("Public file outside public folder")

    return PolicyInfo(
        is_under_public_folder=is_under_public_folder,
        is_public_anyone=is_public_anyone,
        is_public_by_domain=is_public_by_domain,
        public_outside_public_folder=public_outside_public_folder,
        notes=notes
    )
