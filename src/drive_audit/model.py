from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ShareFileConfig:
    days: int
    role: str


@dataclass
class ModerateDeleteConfig:
    sheet_id: str = ""
    name_marker: str = "+delete"
    scan_roots: List[str] = field(default_factory=list)
    scan_interval_seconds: int = 300
    max_per_run: int = 200
    report_csv: str = "deletions-report.csv"
    use_activity_api: bool = False
    allowed_renamer_domains: List[str] = field(default_factory=list)
    allow_folder_delete: bool = False


@dataclass
class PlanfixEndpointConfig:
    url: str
    token: str


@dataclass
class PlanfixConfig:
    get_child_tasks: PlanfixEndpointConfig
    get_manager: PlanfixEndpointConfig
    get_client_task: PlanfixEndpointConfig
    update_contact: PlanfixEndpointConfig
    role: str
    timeout: int = 120


@dataclass
class HttpConfig:
    port: int
    token: str
    lang: str


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
    limit: Optional[int]
    public_subdir: Optional[str]
    output_dir: str
    yaml_file: str
    files_csv: str
    permissions_csv: str
    writer_subdir: Optional[str] = None
    collect_permissions: bool = True
    collect_permissions_max_level: Optional[int] = None
    list_folder_children_cache_timeout: int = 3600

    @staticmethod
    def _resolve_root_folder_id(root_folder_id: Optional[str], drive_id: str) -> str:
        if root_folder_id == "ROOT_FOLDER_ID":
            return drive_id or "root"
        if not root_folder_id:
            return drive_id or "root"
        return root_folder_id

    @staticmethod
    def from_dict(config_data: Dict[str, Any]) -> "DriveConfig":
        drive_section = config_data["drive"]
        google_section = config_data["google"]
        scan_section = config_data.get("scan", {})
        output_section = config_data.get("output", {})
        cache_section = config_data.get("cache_timeouts", {})

        drive_id = drive_section.get("id", "")
        root_folder_id = DriveConfig._resolve_root_folder_id(
            drive_section.get("root_folder_id"), drive_id
        )

        return DriveConfig(
            credentials_file=google_section["credentials_file"],
            delegated_user=google_section.get("delegated_user"),
            drive_id=drive_id,
            root_folder_id=root_folder_id,
            root_folder_name=drive_section["root_folder_name"],
            include_trashed=scan_section.get("include_trashed", False),
            include_shortcuts=scan_section.get("include_shortcuts", True),
            max_depth=scan_section.get("max_depth"),
            limit=scan_section.get("limit"),
            public_subdir=scan_section.get("public_subdir"),
            writer_subdir=drive_section.get("writer_subdir"),
            collect_permissions=scan_section.get("collect_permissions", True),
            collect_permissions_max_level=scan_section.get(
                "collect_permissions_max_level"
            ),
            output_dir=output_section.get("dir", "./data"),
            yaml_file=output_section.get("yaml_file", "drive_audit.yml"),
            files_csv=output_section.get("files_csv", "files.csv"),
            permissions_csv=output_section.get("permissions_csv", "permissions.csv"),
            list_folder_children_cache_timeout=int(
                cache_section.get("list_folder_children", 3600)
            ),
        )


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
    parent_id: Optional[str] = None
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
