"""Location normalization module for comparing file locations.

This module provides simplified location normalization that replaces
basic forbidden characters (/, :, ?) with underscores, without complex
path flattening/unflattening logic.
"""
import re
from pathlib import Path
from typing import Dict

from .compare import (
    MIME_NORMALIZATION_GROUPS,
    normalize_file_name,
    normalize_unicode,
    remove_duplicate_suffix,
)


class LocationNormalizer:
    """Simplified location normalizer that replaces basic characters."""

    def __init__(
        self,
        normalize_file_names: bool = False,
        ignore_duplicate_suffixes: bool = False,
    ):
        """
        Initialize the normalizer.

        Args:
            normalize_file_names: If True, normalize file/folder names in path
            ignore_duplicate_suffixes: If True, remove duplicate suffixes like (1), (2) from file names
        """
        self.normalize_file_names = normalize_file_names
        self.ignore_duplicate_suffixes = ignore_duplicate_suffixes

    def normalize(self, row: Dict[str, str]) -> str:
        """
        Normalize location for comparison.

        Simplified algorithm:
        1. Normalize Unicode
        2. Replace all / and - with _ (for comparison, we don't care where they were)
        3. Apply normalize_file_name to replace other forbidden characters (:, ? → _)
        4. Remove duplicate suffixes (if requested)
        5. Normalize MIME types (remove extension if in same group) - once
        6. Final cleanup of trailing spaces/underscores

        Args:
            row: CSV row with location, mimeType fields

        Returns:
            Normalized location string
        """
        location = (row.get("location") or "").strip()
        if not location:
            return location

        # Step 1: Normalize Unicode
        location = normalize_unicode(location)

        # Step 2: Replace all / and - with _ for comparison
        # This simplifies comparison - we don't care where / or - was (path separator or in filename)
        # Replace / first, then - to ensure consistent normalization
        location = location.replace("/", "_")
        location = location.replace("-", "_")
        
        # Step 3: Apply normalize_file_name to replace other forbidden characters
        # This replaces :, ? and other forbidden chars with _
        if self.normalize_file_names:
            # Normalize the entire location string
            location = normalize_file_name(location, replace_with="_")
            # Normalize spaces around underscores: " _ " -> "_", " _" -> "_", "_ " -> "_"
            location = re.sub(r"\s+_\s+", "_", location)
            location = location.replace(" _", "_").replace("_ ", "_")
        else:
            # Even without normalize_file_names, we still need to handle URL patterns
            # Replace :// and :/ patterns
            location = re.sub(r':/+/?', '_', location)
            # Replace other forbidden characters that might cause issues
            location = location.replace('?', '_').replace(':', '_')

        # Step 4: Remove duplicate suffixes if requested
        if self.ignore_duplicate_suffixes:
            # Since we already replaced all / with _, we can work with the entire location
            # Find the last part (after last _) or use entire location if no _
            last_underscore = location.rfind("_")
            if last_underscore >= 0:
                last_part = location[last_underscore + 1:]
                if "." in last_part:
                    normalized_last = remove_duplicate_suffix(last_part)
                    location = location[: last_underscore + 1] + normalized_last
            else:
                # No underscore, entire location is the filename
                if "." in location:
                    location = remove_duplicate_suffix(location)

        # Step 5: Normalize MIME types (remove extension if in same group) - once
        # Also remove all extensions recursively (handles cases like .csv.xlsx)
        mime_type = (row.get("mimeType") or row.get("mime_type") or "").strip()
        
        # Remove all extensions recursively until no more extensions found
        # This handles cases like "file.csv.xlsx" -> "file"
        # We remove all extensions for comparison, regardless of MIME groups
        max_iterations = 10  # Safety limit to avoid infinite loops
        iteration = 0
        while iteration < max_iterations:
            location_for_suffix = location.rstrip("_")
            suffix = Path(location_for_suffix).suffix.lower()
            
            if not suffix or len(suffix) <= 1:
                break  # No extension found
            
            # Remove the extension
            suffix_len = len(suffix)
            # Handle trailing underscore before extension (e.g., "file_.xlsx")
            if location.lower().endswith("_" + suffix):
                location = location[: -(suffix_len + 1)]
            elif location.lower().endswith(suffix + "_"):
                location = location[: -(suffix_len + 1)]
            elif location.lower().endswith(suffix):
                location = location[: -suffix_len]
            location = location.rstrip("_")
            iteration += 1

        # Step 6: Final cleanup - remove trailing underscores before extensions
        location = re.sub(r"_(\.[^.]+)$", r"\1", location)

        # Step 7: Strip trailing spaces, underscores, and dots
        # This handles cases like "file." -> "file" and "file_." -> "file"
        location = location.rstrip(" _.")

        return location


def normalize_location(
    row: Dict[str, str],
    normalize_file_names: bool = False,
    ignore_duplicate_suffixes: bool = False,
) -> str:
    """
    Normalize location for comparison - simplified version.

    This is a simplified version that replaces all / and - with _ (regardless of where
    they appear), and other forbidden characters (:, ?) with underscores, without
    complex path flattening/unflattening logic.

    Args:
        row: CSV row with location, mimeType fields
        normalize_file_names: If True, normalize file/folder names in path
        ignore_duplicate_suffixes: If True, remove duplicate suffixes like (1), (2) from file names

    Returns:
        Normalized location string
    """
    normalizer = LocationNormalizer(
        normalize_file_names=normalize_file_names,
        ignore_duplicate_suffixes=ignore_duplicate_suffixes,
    )
    return normalizer.normalize(row)

