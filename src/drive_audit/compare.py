"""Functions for comparing file lists from CSV exports."""
import csv
import re
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from unicodedata import normalize

from loguru import logger

DEFAULT_COMPARE_NEW_PATH = Path("data") / "compare_only_new.csv"
DEFAULT_COMPARE_OLD_PATH = Path("data") / "compare_only_old.csv"
DEFAULT_COMPARE_FORMAT_MISMATCHES_PATH = Path("data") / "compare_format_mismatches.csv"


# Google Workspace export formats mapping
# Based on: https://developers.google.com/workspace/drive/api/guides/ref-export-formats
# When downloading Google Drive files as ZIP, Google formats are exported to other formats
MIME_NORMALIZATION_GROUPS = {
    # Google Docs (application/vnd.google-apps.document)
    # Can export to: .docx, .odt, .rtf, .pdf, .txt, .zip (HTML), .epub, .md
    "document": {
        "mimes": {
            "application/vnd.google-apps.document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.oasis.opendocument.text",  # .odt
            "application/rtf",  # .rtf
            "application/pdf",  # .pdf (from Docs)
            "text/plain",  # .txt
            "application/epub+zip",  # .epub
            "text/markdown",  # .md
        },
        "extensions": {".docx", ".odt", ".rtf", ".pdf", ".txt", ".zip", ".epub", ".md"},
        "partial_exports": set(),  # All exports are full
    },
    # Google Sheets (application/vnd.google-apps.spreadsheet)
    # Can export to: .xlsx, .ods, .pdf, .zip (HTML), .csv (first sheet only), .tsv (first sheet only)
    "spreadsheet": {
        "mimes": {
            "application/vnd.google-apps.spreadsheet",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.oasis.opendocument.spreadsheet",  # .ods
            "application/pdf",  # .pdf (from Sheets)
            "text/csv",  # .csv (first sheet only - PARTIAL)
            "text/tab-separated-values",  # .tsv (first sheet only - PARTIAL)
        },
        "extensions": {".xlsx", ".ods", ".pdf", ".zip", ".csv", ".tsv"},
        "partial_exports": {".csv", ".tsv"},  # CSV/TSV only export first sheet
    },
    # Google Slides (application/vnd.google-apps.presentation)
    # Can export to: .pptx, .odp, .pdf, .txt, .jpg/.png/.svg (first slide only)
    "presentation": {
        "mimes": {
            "application/vnd.google-apps.presentation",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.oasis.opendocument.presentation",  # .odp
            "application/pdf",  # .pdf (from Slides)
            "text/plain",  # .txt
            "image/jpeg",  # .jpg (first slide only - PARTIAL)
            "image/png",  # .png (first slide only - PARTIAL)
            "image/svg+xml",  # .svg (first slide only - PARTIAL)
        },
        "extensions": {".pptx", ".odp", ".pdf", ".txt", ".jpg", ".jpeg", ".png", ".svg"},
        "partial_exports": {".jpg", ".jpeg", ".png", ".svg"},  # Images only export first slide
    },
    # Google Drawings (application/vnd.google-apps.drawing)
    # Can export to: .pdf, .jpg, .png, .svg
    # Note: Download/ZIP often converts to .jpg (raster), which is expected
    "drawing": {
        "mimes": {
            "application/vnd.google-apps.drawing",
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/svg+xml",
        },
        "extensions": {".pdf", ".jpg", ".jpeg", ".png", ".svg"},
        "partial_exports": set(),  # All exports are full (raster conversion is expected)
    },
    # Google Forms (application/vnd.google-apps.form)
    # Exports as: .zip
    "form": {
        "mimes": {
            "application/vnd.google-apps.form",
            "application/zip",
        },
        "extensions": {".zip"},
        "partial_exports": set(),
    },
    # Google Apps Script (application/vnd.google-apps.script)
    # Exports as: .json
    "script": {
        "mimes": {
            "application/vnd.google-apps.script",
            "application/json",
        },
        "extensions": {".json"},
        "partial_exports": set(),
    },
    # Google Vids (application/vnd.google-apps.video)
    # Exports as: .mp4
    "video": {
        "mimes": {
            "application/vnd.google-apps.video",
            "video/mp4",
        },
        "extensions": {".mp4"},
        "partial_exports": set(),
    },
    # Jamboard (application/vnd.google-apps.jam)
    # Exports as: .pdf
    "jam": {
        "mimes": {
            "application/vnd.google-apps.jam",
            "application/pdf",  # .pdf (from Jamboard)
        },
        "extensions": {".pdf"},
        "partial_exports": set(),
    },
    # Generic PDF (not from Google Workspace)
    "pdf": {
        "mimes": {
            "application/pdf",
        },
        "extensions": {".pdf"},
        "partial_exports": set(),
    },
    # Generic image formats
    "image_jpeg": {
        "mimes": {
            "image/jpeg",
        },
        "extensions": {".jpg", ".jpeg"},
        "partial_exports": set(),
    },
    "image_png": {
        "mimes": {
            "image/png",
        },
        "extensions": {".png"},
        "partial_exports": set(),
    },
}


# Windows/Linux forbidden characters in file names
# These cannot be used in file/folder names: < > : " | ? * \ / and control chars (0x00-0x1F)
FORBIDDEN_FILE_NAME_CHARS = {
    '<', '>', ':', '"', '|', '?', '*', '\\', '/'
}
# Add control characters (0x00-0x1F)
FORBIDDEN_FILE_NAME_CHARS.update(chr(i) for i in range(32))

FORBIDDEN_FILE_NAME_CHARS_WITH_SLASH = FORBIDDEN_FILE_NAME_CHARS.copy()
FORBIDDEN_FILE_NAME_CHARS_WITH_SLASH.add('/')


def normalize_unicode(text: str) -> str:
    """
    Normalize Unicode text to NFC (Canonical Composition) form.
    
    This ensures consistent representation of characters like 'й',
    whether they come as single characters or decomposed sequences.
    """
    if not text:
        return text
    return normalize("NFC", text)


def normalize_file_name(name: str, replace_with: str = "_") -> str:
    """
    Normalize file/folder name by replacing forbidden characters.
    
    Replaces characters that cannot be used in file names on Windows/Linux:
    < > : " | ? * \\ / and control characters (0x00-0x1F)
    
    Special handling: URL-like patterns (://) are normalized to single replacement
    to match downloaded file names where :// becomes _.
    
    Args:
        name: File or folder name to normalize
        replace_with: Character to replace forbidden characters with (default: '_')
        
    Returns:
        Normalized name with forbidden characters replaced
    """
    if not name:
        return name
    
    # First, normalize URL-like patterns: :// -> single replacement
    # This handles cases like "https://example" -> "https_example" 
    # to match downloaded names where :// becomes _
    # Handle both :// and :/ patterns
    result = re.sub(r':/+/?', replace_with, name)
    
    # Handle URL-encoded characters (e.g., %2F -> / -> _)
    # Common URL-encoded chars that appear in file names: %2F (/) and others
    # Also handle cases where %2F was already converted to _2F (without decoding)
    # Replace %2F patterns before decoding - convert to / first, then it will be handled as path separator
    # But we need to preserve it as a path separator, not convert to underscore yet
    # So we'll handle _2F first, then %2F
    # Handle case where URL-encoded %2F was already converted to _2F without decoding
    # In new CSV, %2F might appear as _2F (literal text, not decoded)
    # Replace _2F pattern with / to match %2F behavior
    result = re.sub(r'_2F', '/', result)
    
    # Now handle %2F - convert to / (path separator, not underscore)
    result = re.sub(r'%2F', '/', result)
    try:
        # Try to decode any remaining URL-encoded parts
        result = urllib.parse.unquote(result, errors='ignore')
    except Exception:
        pass
    
    # Replace remaining forbidden characters and special cases
    normalized = ""
    for char in result:
        if char in FORBIDDEN_FILE_NAME_CHARS_WITH_SLASH:
            normalized += replace_with
        elif char == "'":  # Handle apostrophes that get replaced with _ when downloaded
            normalized += replace_with
        else:
            normalized += char
    
    # Replace leading/trailing spaces and dots (Windows restriction)
    normalized = normalized.strip(" .")
    
    # Replace multiple consecutive replacements with single one
    # This ensures that :// -> _, and multiple _ become single _
    # But for URL patterns, normalize both "https_www.example_" and "https_www.example__" 
    # to the same form (single underscore) to ensure matching
    # First, normalize double underscores in URL patterns to single underscore
    # Pattern: "https_www.example__" -> "https_www.example_"
    normalized = re.sub(r'(https?_[a-z0-9.-]+)__', r'\1_', normalized, flags=re.IGNORECASE)
    
    # Replace multiple consecutive replacements with single one
    normalized = re.sub(f"{re.escape(replace_with)}+", replace_with, normalized)
    
    return normalized


def remove_duplicate_suffix(name: str) -> str:
    """
    Remove duplicate suffix from file name.
    
    Removes patterns like (1), (2), (10), etc. before the file extension.
    Example: "file(1).pdf" -> "file.pdf", "document(2).docx" -> "document.docx"
    
    Args:
        name: File or folder name
        
    Returns:
        Name with duplicate suffix removed, or original name if no suffix found
    """
    if not name:
        return name
    
    # Pattern to match (N) before extension: (1).pdf, (2).docx, etc.
    # Match (digits) followed by .extension at the end
    duplicate_pattern = re.compile(r'\((\d+)\)(\.[^.]+)$')
    
    match = duplicate_pattern.search(name)
    if match:
        # Replace (N).ext with .ext
        return duplicate_pattern.sub(r'\2', name)
    
    return name


# normalize_location is imported from location_normalizer module using lazy import
# inside compare_files_by_location function to avoid circular import
# The old complex implementation has been replaced with a simplified version
# that only replaces basic forbidden characters (/, :, ?) with underscores


def should_ignore_public_subdir_row(
    row: Dict[str, str], public_subdir: Optional[str], ignore_public_subdir: bool
) -> bool:
    """
    Check if a row should be ignored because it's the public_subdir folder itself.
    
    Ignores the folder itself (e.g., /Client/public) but not its children
    (e.g., /Client/public/file.txt).
    
    Args:
        row: CSV row with location, type, and mime_type fields
        public_subdir: Name of the public subdirectory (e.g., "public")
        ignore_public_subdir: Whether to ignore public_subdir folders
        
    Returns:
        True if this row should be ignored, False otherwise
    """
    if not ignore_public_subdir or not public_subdir:
        return False
    
    location = (row.get("location") or "").strip()
    if not location:
        return False
    
    # Check if location ends with /{public_subdir} (the folder itself)
    # But not /{public_subdir}/something (files inside)
    if location.endswith(f"/{public_subdir}"):
        # Check if this is actually a folder
        mime_type = (row.get("mimeType") or row.get("mime_type") or "").strip()
        file_type = (row.get("type") or "").strip().lower()
        
        # It's a folder if mime_type contains "folder" or type is "folder"
        is_folder = (
            "folder" in mime_type.lower() or file_type == "folder"
        )
        
        if is_folder:
            return True
    
    return False


def should_ignore_folder_row(
    row: Dict[str, str],
    all_rows: List[Dict[str, str]],
    ignore_folders: List[str],
) -> bool:
    """
    Check if a row should be ignored based on ignore_folders list.
    
    Ignores:
    1. Folders that have a name matching one in ignore_folders list
    2. Any row (file or folder) whose location is inside an ignored folder
    
    Args:
        row: CSV row with location, type, mime_type, and name fields
        all_rows: All CSV rows to find ignored folder locations
        ignore_folders: List of folder names to ignore
        
    Returns:
        True if this row should be ignored, False otherwise
    """
    if not ignore_folders:
        return False
    
    location = (row.get("location") or "").strip()
    if not location:
        return False
    
    # Normalize location for consistent comparison
    location = normalize_unicode(location)
    
    # Normalize ignore_folders list for comparison
    normalized_ignore_folders = [normalize_unicode(folder.strip()) for folder in ignore_folders]
    
    # First, find all ignored folder locations from all_rows
    ignored_folder_locations = set()
    for other_row in all_rows:
        other_location = normalize_unicode((other_row.get("location") or "").strip())
        if not other_location:
            continue
        
        # Check if this row is a folder that matches ignore_folders
        other_mime_type = (other_row.get("mimeType") or other_row.get("mime_type") or "").strip()
        other_file_type = (other_row.get("type") or "").strip().lower()
        is_other_folder = "folder" in other_mime_type.lower() or other_file_type == "folder"
        
        if is_other_folder:
            # Get folder name from name field or extract from location
            other_folder_name_from_field = normalize_unicode((other_row.get("name") or "").strip())
            other_location_parts = other_location.strip("/").split("/")
            other_folder_name_from_location = ""
            if other_location_parts:
                other_folder_name_from_location = normalize_unicode(other_location_parts[-1])
            
            # Check if folder name matches any in ignore_folders
            if (other_folder_name_from_field in normalized_ignore_folders or
                other_folder_name_from_location in normalized_ignore_folders):
                # Add this folder location to ignored set
                ignored_folder_locations.add(other_location.rstrip("/"))
    
    # Check if current row's location is inside any ignored folder
    location_normalized = location.rstrip("/")
    for ignored_location in ignored_folder_locations:
        # Check if location is the ignored folder itself or inside it
        if location_normalized == ignored_location or location.startswith(ignored_location + "/"):
            return True
    
    return False


def read_csv_rows(csv_path: Path) -> tuple[List[Dict[str, str]], Sequence[str]]:
    """Read CSV rows and return list of rows and fieldnames."""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    if not csv_path.is_file():
        raise ValueError(f"CSV path must be a file: {csv_path}")

    with csv_path.open(encoding="utf-8-sig", newline="") as csv_handle:
        reader = csv.DictReader(csv_handle)
        if not reader.fieldnames or "location" not in reader.fieldnames:
            raise ValueError(
                "CSV must include a 'location' column to support comparison"
            )
        rows = [row for row in reader]

    return rows, reader.fieldnames


def build_fieldnames(primary: Sequence[str], secondary: Sequence[str]) -> List[str]:
    """Merge two sequences of fieldnames, preserving order. Location column is always first."""
    if list(primary) == list(secondary):
        fieldnames = list(primary)
    else:
        merged: List[str] = []
        for field in primary:
            if field not in merged:
                merged.append(field)
        for field in secondary:
            if field not in merged:
                merged.append(field)
        fieldnames = merged
    
    # Move "location" to first position if it exists
    if "location" in fieldnames:
        fieldnames.remove("location")
        fieldnames.insert(0, "location")
    
    return fieldnames


def compare_files_by_location(
    csv_old: Path,
    csv_new: Path,
    output_new_path: Path = DEFAULT_COMPARE_NEW_PATH,
    output_old_path: Path = DEFAULT_COMPARE_OLD_PATH,
    output_format_mismatches_path: Optional[Path] = None,
    ignore_public_subdir: bool = False,
    public_subdir: Optional[str] = None,
    normalize_file_names: bool = False,
    ignore_format_differences: bool = False,
    ignore_duplicate_suffixes: bool = False,
    ignore_folders: Optional[List[str]] = None,
) -> Dict[str, Any]:
    old_rows, old_fields = read_csv_rows(csv_old)
    new_rows, new_fields = read_csv_rows(csv_new)

    combined_fieldnames = build_fieldnames(old_fields, new_fields)

    # Track statistics
    stats = {
        "ignored_public_subdirs_old": 0,
        "ignored_public_subdirs_new": 0,
        "ignored_folders_old": 0,
        "ignored_folders_new": 0,
        "total_rows_old": len(old_rows),
        "total_rows_new": len(new_rows),
    }

    # Filter out public_subdir folders if configured
    if ignore_public_subdir:
        ignored_old = [
            row
            for row in old_rows
            if should_ignore_public_subdir_row(row, public_subdir, ignore_public_subdir)
        ]
        ignored_new = [
            row
            for row in new_rows
            if should_ignore_public_subdir_row(row, public_subdir, ignore_public_subdir)
        ]
        stats["ignored_public_subdirs_old"] = len(ignored_old)
        stats["ignored_public_subdirs_new"] = len(ignored_new)
        
        old_rows = [
            row
            for row in old_rows
            if not should_ignore_public_subdir_row(row, public_subdir, ignore_public_subdir)
        ]
        new_rows = [
            row
            for row in new_rows
            if not should_ignore_public_subdir_row(row, public_subdir, ignore_public_subdir)
        ]
        logger.info(
            "Filtered out public_subdir folders: {} from old CSV, {} from new CSV (public_subdir: {}, ignore: {})",
            stats["ignored_public_subdirs_old"],
            stats["ignored_public_subdirs_new"],
            public_subdir,
            ignore_public_subdir,
        )

    # Filter out folders with children if ignore_folders is configured
    if ignore_folders:
        # Combine all rows to find ignored folder locations (do this once, not per row)
        all_rows = old_rows + new_rows
        
        # Build ignored folder locations set once
        normalized_ignore_folders = [normalize_unicode(folder.strip()) for folder in ignore_folders]
        ignored_folder_locations = set()
        for row in all_rows:
            location = normalize_unicode((row.get("location") or "").strip())
            if not location:
                continue
            
            # Check if this row is a folder that matches ignore_folders
            mime_type = (row.get("mimeType") or row.get("mime_type") or "").strip()
            file_type = (row.get("type") or "").strip().lower()
            is_folder = "folder" in mime_type.lower() or file_type == "folder"
            
            if is_folder:
                # Get folder name from name field or extract from location
                folder_name_from_field = normalize_unicode((row.get("name") or "").strip())
                location_parts = location.strip("/").split("/")
                folder_name_from_location = ""
                if location_parts:
                    folder_name_from_location = normalize_unicode(location_parts[-1])
                
                # Check if folder name matches any in ignore_folders
                if (folder_name_from_field in normalized_ignore_folders or
                    folder_name_from_location in normalized_ignore_folders):
                    # Add this folder location to ignored set
                    ignored_folder_locations.add(location.rstrip("/"))
        
        # Now filter rows using the cached ignored_folder_locations
        def should_ignore_row(row: Dict[str, str]) -> bool:
            location = normalize_unicode((row.get("location") or "").strip())
            if not location:
                return False
            location_normalized = location.rstrip("/")
            for ignored_location in ignored_folder_locations:
                if location_normalized == ignored_location or location.startswith(ignored_location + "/"):
                    return True
            return False
        
        ignored_old = [row for row in old_rows if should_ignore_row(row)]
        ignored_new = [row for row in new_rows if should_ignore_row(row)]
        stats["ignored_folders_old"] = len(ignored_old)
        stats["ignored_folders_new"] = len(ignored_new)
        
        old_rows = [row for row in old_rows if not should_ignore_row(row)]
        new_rows = [row for row in new_rows if not should_ignore_row(row)]
        logger.info(
            "Filtered out folders and their children: {} from old CSV, {} from new CSV (ignore_folders: {})",
            stats["ignored_folders_old"],
            stats["ignored_folders_new"],
            ignore_folders,
        )

    # Lazy import to avoid circular import
    from .location_normalizer import normalize_location

    # Build normalized location maps
    old_by_normalized: Dict[str, List[Dict[str, str]]] = {}
    new_by_normalized: Dict[str, List[Dict[str, str]]] = {}

    for row in old_rows:
        norm_loc = normalize_location(
            row,
            normalize_file_names=normalize_file_names,
            ignore_duplicate_suffixes=ignore_duplicate_suffixes,
        )
        old_by_normalized.setdefault(norm_loc, []).append(row)

    for row in new_rows:
        norm_loc = normalize_location(
            row,
            normalize_file_names=normalize_file_names,
            ignore_duplicate_suffixes=ignore_duplicate_suffixes,
        )
        new_by_normalized.setdefault(norm_loc, []).append(row)

    old_locations = set(old_by_normalized.keys())
    new_locations = set(new_by_normalized.keys())

    new_only_rows = [
        row
        for row in new_rows
        if normalize_location(
            row,
            normalize_file_names=normalize_file_names,
            ignore_duplicate_suffixes=ignore_duplicate_suffixes,
        )
        not in old_locations
    ]
    old_only_rows = [
        row
        for row in old_rows
        if normalize_location(
            row,
            normalize_file_names=normalize_file_names,
            ignore_duplicate_suffixes=ignore_duplicate_suffixes,
        )
        not in new_locations
    ]

    # Find format mismatches: same normalized location but different actual locations
    format_mismatches: List[Dict[str, str]] = []
    if not ignore_format_differences:
        for norm_loc in old_locations & new_locations:
            old_matches = old_by_normalized[norm_loc]
            new_matches = new_by_normalized[norm_loc]

            for old_row in old_matches:
                old_actual_loc = normalize_unicode((old_row.get("location") or "").strip())
                old_mime = old_row.get("mimeType", "").strip()
                old_suffix = Path(old_actual_loc).suffix.lower()

                for new_row in new_matches:
                    new_actual_loc = normalize_unicode((new_row.get("location") or "").strip())
                    new_mime = new_row.get("mimeType", "").strip()
                    new_suffix = Path(new_actual_loc).suffix.lower()

                    if old_actual_loc != new_actual_loc:
                        # Check if either file is a partial export (e.g., CSV from Sheets, image from Slides)
                        old_is_partial = False
                        new_is_partial = False
                        partial_warning = ""
                        
                        # Find which group these files belong to
                        matched_group = None
                        for group_name, group_values in MIME_NORMALIZATION_GROUPS.items():
                            if old_mime in group_values["mimes"] or old_suffix in group_values["extensions"]:
                                matched_group = group_name
                                break
                            if new_mime in group_values["mimes"] or new_suffix in group_values["extensions"]:
                                matched_group = group_name
                                break
                        
                        if matched_group:
                            partial_exports = MIME_NORMALIZATION_GROUPS[matched_group].get("partial_exports", set())
                            if old_suffix in partial_exports:
                                old_is_partial = True
                            if new_suffix in partial_exports:
                                new_is_partial = True
                            
                            if old_is_partial or new_is_partial:
                                if matched_group == "spreadsheet":
                                    partial_warning = "WARNING: CSV/TSV exports only contain first sheet"
                                elif matched_group == "presentation":
                                    partial_warning = "WARNING: Image exports only contain first slide"
                        
                        mismatch_row = {
                            "normalized_location": norm_loc,
                            "old_location": old_actual_loc,
                            "old_mime_type": old_mime,
                            "old_file_id": old_row.get("file_id", ""),
                            "old_name": old_row.get("name", ""),
                            "new_location": new_actual_loc,
                            "new_mime_type": new_mime,
                            "new_file_id": new_row.get("file_id", ""),
                            "new_name": new_row.get("name", ""),
                            "partial_export_warning": partial_warning,
                        }
                        format_mismatches.append(mismatch_row)

    def write_rows(rows: List[Dict[str, str]], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Sort rows by location (case-insensitive) for easier comparison
        sorted_rows = sorted(rows, key=lambda r: (r.get("location") or "").lower())
        # Only include specific columns: location, client_name, mime_type, modified
        result_fieldnames = ["location", "client_name", "mime_type", "modified"]
        with output_path.open("w", newline="", encoding="utf-8") as csv_handle:
            writer = csv.DictWriter(csv_handle, fieldnames=result_fieldnames)
            writer.writeheader()
            for row in sorted_rows:
                # Map mimeType to mime_type if needed
                mime_type = row.get("mime_type") or row.get("mimeType") or ""
                writer.writerow({
                    "location": row.get("location", ""),
                    "client_name": row.get("client_name", ""),
                    "mime_type": mime_type,
                    "modified": row.get("modified", ""),
                })
        return output_path

    output_new = write_rows(new_only_rows, output_new_path)
    output_old = write_rows(old_only_rows, output_old_path)

    stats["new_only_rows"] = len(new_only_rows)
    stats["old_only_rows"] = len(old_only_rows)

    logger.info(
        "Wrote {} new-only rows to {} and {} old-only rows to {}",
        len(new_only_rows),
        output_new,
        len(old_only_rows),
        output_old,
    )

    result = {"new": output_new, "old": output_old, "stats": stats}

    if format_mismatches:
        if output_format_mismatches_path is None:
            output_format_mismatches_path = DEFAULT_COMPARE_FORMAT_MISMATCHES_PATH

        mismatch_fieldnames = [
            "normalized_location",
            "old_location",
            "old_mime_type",
            "old_file_id",
            "old_name",
            "new_location",
            "new_mime_type",
            "new_file_id",
            "new_name",
            "partial_export_warning",
        ]
        output_format_mismatches_path.parent.mkdir(parents=True, exist_ok=True)
        # Sort format mismatches by normalized_location for easier comparison
        sorted_format_mismatches = sorted(format_mismatches, key=lambda r: (r.get("normalized_location") or "").lower())
        with output_format_mismatches_path.open("w", newline="", encoding="utf-8") as csv_handle:
            writer = csv.DictWriter(csv_handle, fieldnames=mismatch_fieldnames)
            writer.writeheader()
            for row in sorted_format_mismatches:
                writer.writerow(row)

        logger.info(
            "Found {} format mismatches (same file, different format) written to {}",
            len(format_mismatches),
            output_format_mismatches_path,
        )
        result["format_mismatches"] = output_format_mismatches_path

    return result
