import csv
from typing import List
from .model import FileInfo

def save_files_csv(files: List[FileInfo], output_path: str):
    """Exports flat file list to CSV."""
    fieldnames = [
        'file_id', 'name', 'type', 'mime_type', 'client_name', 'location', 'depth',
        'is_shortcut', 'shortcut_target_id', 'created', 'modified', 'viewed',
        'owner_email', 'last_modifying_user_email', 'size_bytes',
        'general_access', 'general_role', 'general_domain', 'general_has_link_sharing',
        'policy_is_under_public_folder', 'policy_is_public_anyone',
        'policy_is_public_by_domain', 'policy_public_outside_public_folder'
    ]
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for f in files:
            row = {
                'file_id': f.id,
                'name': f.name,
                'type': f.type,
                'mime_type': f.mime_type,
                'client_name': f.client_name,
                'location': f.location,
                'depth': f.depth,
                'is_shortcut': f.is_shortcut,
                'shortcut_target_id': f.shortcut_target_id,
                'created': f.created,
                'modified': f.modified,
                'viewed': f.viewed,
                'owner_email': f.owners[0].get('emailAddress') if f.owners else None,
                'last_modifying_user_email': f.last_modifying_user.get('emailAddress') if f.last_modifying_user else None,
                'size_bytes': f.size_bytes,
                'general_access': f.access.general_access,
                'general_role': f.access.general_role,
                'general_domain': f.access.general_domain,
                'general_has_link_sharing': f.access.has_link_sharing,
                'policy_is_under_public_folder': f.policy.is_under_public_folder,
                'policy_is_public_anyone': f.policy.is_public_anyone,
                'policy_is_public_by_domain': f.policy.is_public_by_domain,
                'policy_public_outside_public_folder': f.policy.public_outside_public_folder
            }
            writer.writerow(row)

def save_permissions_csv(files: List[FileInfo], output_path: str):
    """Exports detailed permissions list to CSV."""
    fieldnames = [
        'file_id', 'file_name', 'location', 'client_name',
        'permission_id', 'permission_type', 'permission_role',
        'permission_email', 'permission_domain', 'display_name',
        'allow_file_discovery', 'expiration', 'deleted',
        'inherited', 'inherited_from_id', 'inherited_from_location'
    ]
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for f in files:
            for p in f.access.permissions:
                # Calculate aggregated inherited status
                inherited = None
                if p.permission_details:
                    # Logic: True if all are true, False if any is false
                    all_true = True
                    for d in p.permission_details:
                        if not d.inherited:
                            all_true = False
                            break
                    inherited = all_true
                
                inherited_from_id = None
                for d in p.permission_details:
                    if d.inherited_from:
                        inherited_from_id = d.inherited_from
                        break
                        
                row = {
                    'file_id': f.id,
                    'file_name': f.name,
                    'location': f.location,
                    'client_name': f.client_name,
                    'permission_id': p.id,
                    'permission_type': p.type,
                    'permission_role': p.role,
                    'permission_email': p.email,
                    'permission_domain': p.domain,
                    'display_name': p.display_name,
                    'allow_file_discovery': p.allow_file_discovery,
                    'expiration': p.expiration,
                    'deleted': p.deleted,
                    'inherited': inherited,
                    'inherited_from_id': inherited_from_id,
                    'inherited_from_location': None # Requires lookup map, skipping for now
                }
                writer.writerow(row)
