"""Credential loading shared by Google API service factories."""

import json
import os
from typing import List, Optional

from google.oauth2 import credentials as user_credentials
from google.oauth2 import service_account

from .model import DriveConfig


def load_credentials(
    config: DriveConfig,
    service_account_scopes: List[str],
    *,
    authorized_user_scopes: Optional[List[str]] = None,
):
    """Load either service-account or authorized-user JSON credentials."""
    path = config.credentials_file
    if not os.path.exists(path):
        raise FileNotFoundError(f"Credentials file not found: {path}")

    with open(path, encoding="utf-8") as handle:
        credential_type = str((json.load(handle) or {}).get("type") or "")

    if credential_type == "service_account":
        credentials = service_account.Credentials.from_service_account_file(
            path,
            scopes=service_account_scopes,
        )
        if config.delegated_user:
            credentials = credentials.with_subject(config.delegated_user)
        return credentials

    if credential_type == "authorized_user":
        if config.delegated_user:
            raise ValueError(
                "google.delegated_user is only supported for service-account "
                "credentials"
            )
        credentials = user_credentials.Credentials.from_authorized_user_file(path)
        required_scopes = set(authorized_user_scopes or service_account_scopes)
        granted_scopes = set(credentials.scopes or [])
        missing_scopes = sorted(required_scopes - granted_scopes)
        if missing_scopes:
            raise ValueError(
                "Authorized-user credentials are missing required scopes: "
                + ", ".join(missing_scopes)
            )
        return credentials

    raise ValueError(
        "Unsupported Google credentials type "
        f"{credential_type or '<missing>'!r} in {path}"
    )


__all__ = ["load_credentials"]
