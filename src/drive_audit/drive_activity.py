"""Drive Activity helpers for resolving who added a filename deletion marker."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from loguru import logger

from .credentials import load_credentials
from .model import DriveConfig

ACTIVITY_SCOPES = ["https://www.googleapis.com/auth/drive.activity.readonly"]
PEOPLE_SCOPES = ["https://www.googleapis.com/auth/directory.readonly"]
PEOPLE_USER_SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


@dataclass(frozen=True)
class RenameEvent:
    """The most recent rename that added the configured marker."""

    previous_name: str
    new_name: str
    renamed_at: str
    renamed_by: str
    renamer_name: str
    renamer_email: str
    renamer_domain: str
    person_name: str


def get_activity_service(config: DriveConfig):
    """Authenticate and return an isolated Drive Activity v2 service."""
    credentials = load_credentials(config, ACTIVITY_SCOPES)
    return build("driveactivity", "v2", credentials=credentials)


def get_people_service(config: DriveConfig):
    """Authenticate and return an isolated People v1 service."""
    credentials = load_credentials(
        config,
        PEOPLE_SCOPES,
        authorized_user_scopes=PEOPLE_USER_SCOPES,
    )
    return build("people", "v1", credentials=credentials)


class RenameActivityResolver:
    """Resolve the actor and timestamp of a rename that added ``+delete``."""

    def __init__(self, activity_service, people_service, drive_service=None):
        self._activity = activity_service
        self._people = people_service
        self._drive = drive_service
        self._activities_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._profile_cache: Dict[str, Dict[str, str]] = {}

    def clear_activity_cache(self) -> None:
        """Force the next scan/apply to observe fresh rename activity."""
        self._activities_cache.clear()

    def _query_activities(self, file_id: str) -> List[Dict[str, Any]]:
        if file_id in self._activities_cache:
            return self._activities_cache[file_id]

        activities: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        while True:
            body: Dict[str, Any] = {
                "itemName": f"items/{file_id}",
                "filter": "detail.action_detail_case:RENAME",
                "pageSize": 100,
                "consolidationStrategy": {"none": {}},
            }
            if page_token:
                body["pageToken"] = page_token

            # The generated Python client exposes the singular ``activity``
            # resource, matching REST resource v2.activity.
            response = self._activity.activity().query(body=body).execute()
            activities.extend(response.get("activities", []) or [])
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        self._activities_cache[file_id] = activities
        return activities

    @staticmethod
    def _rename_detail(activity: Dict[str, Any]) -> Optional[Dict[str, str]]:
        primary = activity.get("primaryActionDetail") or {}
        rename = primary.get("rename")
        if rename:
            return rename

        for action in activity.get("actions", []) or []:
            action_detail = action.get("detail") or action.get("actionDetail") or {}
            rename = action_detail.get("rename")
            if rename:
                return rename
        return None

    @staticmethod
    def _activity_time(activity: Dict[str, Any]) -> str:
        if activity.get("timestamp"):
            return str(activity["timestamp"])
        time_range = activity.get("timeRange") or {}
        return str(time_range.get("endTime") or time_range.get("startTime") or "")

    @staticmethod
    def _time_sort_key(value: str) -> datetime:
        if not value:
            return datetime.min
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except ValueError:
            return datetime.min

    @staticmethod
    def _person_name_from_actor(actor: Dict[str, Any]) -> str:
        known_user = ((actor.get("user") or {}).get("knownUser")) or {}
        if known_user.get("personName"):
            return str(known_user["personName"])
        if known_user.get("isCurrentUser"):
            return "people/me"
        return ""

    @classmethod
    def _person_name(cls, activity: Dict[str, Any]) -> str:
        for actor in activity.get("actors", []) or []:
            person_name = cls._person_name_from_actor(actor)
            if person_name:
                return person_name

        for action in activity.get("actions", []) or []:
            person_name = cls._person_name_from_actor(action.get("actor") or {})
            if person_name:
                return person_name
        return ""

    @classmethod
    def _drive_profile(
        cls,
        file_id: str,
        renamed_at: str,
        metadata: Optional[Dict[str, Any]],
        drive_service,
    ) -> Dict[str, str]:
        if not file_id or not renamed_at:
            return {}

        if metadata is None and drive_service is not None:
            try:
                metadata = (
                    drive_service.files()
                    .get(
                        fileId=file_id,
                        supportsAllDrives=True,
                        fields=(
                            "modifiedTime,"
                            "lastModifyingUser(displayName,emailAddress)"
                        ),
                    )
                    .execute()
                )
            except Exception as error:
                logger.debug(
                    "Drive last-modifier lookup failed for {}: {}", file_id, error
                )
                return {}

        metadata = metadata or {}
        modified_at = str(metadata.get("modifiedTime") or "")
        try:
            delta = abs(
                (
                    cls._time_sort_key(modified_at) - cls._time_sort_key(renamed_at)
                ).total_seconds()
            )
        except (OverflowError, ValueError):
            return {}
        if not modified_at or delta > 5:
            return {}

        modifier = metadata.get("lastModifyingUser") or {}
        profile: Dict[str, str] = {}
        if modifier.get("emailAddress"):
            profile["email"] = str(modifier["emailAddress"])
        if modifier.get("displayName"):
            profile["display_name"] = str(modifier["displayName"])
        return profile

    def _resolve_profile(
        self,
        person_name: str,
        file_id: str,
        renamed_at: str,
        file_metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, str]:
        if not person_name:
            return {}

        cached = self._profile_cache.get(person_name)
        if cached is None:
            cached = {}
            try:
                person = (
                    self._people.people()
                    .get(
                        resourceName=person_name,
                        personFields="names,emailAddresses",
                    )
                    .execute()
                )
            except Exception as error:
                logger.debug("People lookup failed for {}: {}", person_name, error)
                person = {}

            emails = person.get("emailAddresses", []) or []
            primary_email = next(
                (
                    entry
                    for entry in emails
                    if (entry.get("metadata") or {}).get("primary")
                ),
                emails[0] if emails else None,
            )
            if primary_email and primary_email.get("value"):
                cached["email"] = str(primary_email["value"])

            names = person.get("names", []) or []
            primary_name = next(
                (
                    entry
                    for entry in names
                    if (entry.get("metadata") or {}).get("primary")
                ),
                names[0] if names else None,
            )
            if primary_name and primary_name.get("displayName"):
                cached["display_name"] = str(primary_name["displayName"])

            self._profile_cache[person_name] = cached

        profile = dict(cached)
        if not profile.get("email") or not profile.get("display_name"):
            fallback = self._drive_profile(
                file_id,
                renamed_at,
                file_metadata,
                self._drive,
            )
            profile.setdefault("email", fallback.get("email", ""))
            profile.setdefault("display_name", fallback.get("display_name", ""))
        return {key: value for key, value in profile.items() if value}

    @staticmethod
    def _renamed_by(profile: Dict[str, str], person_name: str) -> str:
        email = profile.get("email", "")
        display_name = profile.get("display_name", "")
        if display_name and email:
            return f"{display_name} <{email}>"
        if display_name:
            return display_name
        if email:
            return email
        if person_name == "people/me":
            return "current-user"
        return person_name

    def resolve_rename(
        self,
        file_id: str,
        current_name: str,
        marker: str,
        file_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[RenameEvent]:
        """Return the latest rename that produced the current marked name.

        Any Activity or People API failure is fail-closed for callers that use a
        domain allow-list: this method returns ``None`` or an event without a
        domain, and the caller excludes the candidate.
        """
        try:
            matching: List[tuple[str, Dict[str, str], Dict[str, Any]]] = []
            marker_folded = marker.casefold()
            for activity in self._query_activities(file_id):
                rename = self._rename_detail(activity)
                if not rename:
                    continue
                new_name = str(rename.get("newTitle") or "")
                if marker_folded not in new_name.casefold():
                    continue
                if current_name and new_name != current_name:
                    continue
                matching.append((self._activity_time(activity), rename, activity))

            if not matching:
                logger.debug(
                    "No rename activity added marker {} to {}", marker, file_id
                )
                return None

            renamed_at, rename, activity = max(
                matching, key=lambda item: self._time_sort_key(item[0])
            )
            person_name = self._person_name(activity)
            profile = self._resolve_profile(
                person_name,
                file_id,
                renamed_at,
                file_metadata,
            )
            email = profile.get("email", "")
            display_name = profile.get("display_name", "")
            domain = email.rsplit("@", 1)[1].lower() if "@" in email else ""
            renamed_by = self._renamed_by(profile, person_name)

            return RenameEvent(
                previous_name=str(rename.get("oldTitle") or ""),
                new_name=str(rename.get("newTitle") or current_name),
                renamed_at=renamed_at,
                renamed_by=renamed_by,
                renamer_name=display_name,
                renamer_email=email,
                renamer_domain=domain,
                person_name=person_name,
            )
        except Exception as error:
            logger.warning(
                "Rename activity resolution failed for {} (excluded by strict "
                "domain mode): {}",
                file_id,
                error,
            )
            return None


__all__ = [
    "ACTIVITY_SCOPES",
    "PEOPLE_SCOPES",
    "PEOPLE_USER_SCOPES",
    "RenameActivityResolver",
    "RenameEvent",
    "get_activity_service",
    "get_people_service",
]
