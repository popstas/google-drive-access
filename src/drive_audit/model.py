from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime

@dataclass
class DriveConfig:
    credentials_file: str
    delegated_user: Optional[str]
    drive_id: str
    root_folder_id: str
    root_folder_name: str
    include_trashed: bool
    include_shortcuts: bool
    max_depth: Optional[int]
    public_folder_name: str
    output_dir: str
    yaml_file: str
    files_csv: str
    permissions_csv: str

@dataclass
class PermissionDetails:
    permission_type: str
    role: str
    inherited: bool
    inherited_from: Optional[str]

@dataclass
class Permission:
    id: str
    type: str
    role: str
    email: Optional[str] = None
    domain: Optional[str] = None
    display_name: Optional[str] = None
    allow_file_discovery: Optional[bool] = None
    expiration: Optional[datetime] = None
    deleted: Optional[bool] = None
    permission_details: List[PermissionDetails] = field(default_factory=list)

@dataclass
class AccessInfo:
    inherited: bool
    inherited_from_id: Optional[str]
    inherited_from_name: Optional[str]
    inherited_from_location: Optional[str]
    general_access: str  # restricted | domain | anyone
    general_role: Optional[str]
    general_domain: Optional[str]
    allow_file_discovery: Optional[bool]
    has_link_sharing: bool
    permissions: List[Permission] = field(default_factory=list)

@dataclass
class PolicyInfo:
    is_under_public_folder: bool
    is_public_anyone: bool
    is_public_by_domain: bool
    public_outside_public_folder: bool
    notes: List[str] = field(default_factory=list)

@dataclass
class FileInfo:
    id: str
    name: str
    type: str  # file | folder | shortcut
    mime_type: str
    parents: List[Dict[str, str]]
    created: datetime
    modified: datetime
    viewed: Optional[datetime]
    trashed: bool
    starred: bool
    size_bytes: Optional[int]
    owners: List[Dict[str, str]]
    last_modifying_user: Optional[Dict[str, str]]
    
    # Enriched fields
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    location: str = ""
    depth: int = 0
    
    # Shortcut specific
    is_shortcut: bool = False
    shortcut_target_id: Optional[str] = None
    shortcut_target_type: Optional[str] = None
    shortcut_target_mime_type: Optional[str] = None
    
    # Access & Policy
    access: Optional[AccessInfo] = None
    policy: Optional[PolicyInfo] = None
