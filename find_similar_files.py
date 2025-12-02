#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find similar files and analyze normalization patterns."""
import csv
import sys
from difflib import SequenceMatcher
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def similarity(a: str, b: str) -> float:
    """Calculate similarity ratio between two strings."""
    return SequenceMatcher(None, a, b).ratio()


def find_similar_files(
    old_csv: Path, new_csv: Path, output_csv: Path, threshold: float = 0.95
):
    """Find similar files with location similarity >= threshold."""
    print(f"Reading {old_csv}...")
    old_rows = list(csv.DictReader(open(old_csv, encoding="utf-8-sig")))
    print(f"Reading {new_csv}...")
    new_rows = list(csv.DictReader(open(new_csv, encoding="utf-8-sig")))

    print(f"Old CSV: {len(old_rows)} files")
    print(f"New CSV: {len(new_rows)} files")

    similar_pairs = []
    print("Comparing files...")
    for idx, old_row in enumerate(old_rows, 1):
        if idx % 10 == 0:
            print(f"  Processed {idx}/{len(old_rows)} old files...")
        old_loc = (old_row.get("location") or "").strip()
        if not old_loc:
            continue
        for new_row in new_rows:
            new_loc = (new_row.get("location") or "").strip()
            if not new_loc:
                continue
            sim = similarity(old_loc, new_loc)
            if sim >= threshold:
                similar_pairs.append(
                    {
                        "similarity": f"{sim:.4f}",
                        "old_location": old_loc,
                        "old_file_id": old_row.get("file_id", ""),
                        "old_name": old_row.get("name", ""),
                        "old_mime_type": old_row.get("mimeType", ""),
                        "new_location": new_loc,
                        "new_file_id": new_row.get("file_id", ""),
                        "new_name": new_row.get("name", ""),
                        "new_mime_type": new_row.get("mimeType", ""),
                    }
                )

    similar_pairs.sort(key=lambda x: float(x["similarity"]), reverse=True)
    print(f"\nFound {len(similar_pairs)} pairs with similarity >= {threshold}")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "similarity",
        "old_location",
        "old_file_id",
        "old_name",
        "old_mime_type",
        "new_location",
        "new_file_id",
        "new_name",
        "new_mime_type",
    ]
    with output_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if similar_pairs:
            writer.writerows(similar_pairs)

    if similar_pairs:
        print(f"Saved {len(similar_pairs)} pairs to {output_csv}")

        # Analyze patterns
        print("\n=== Pattern Analysis ===")
        patterns = {}
        for pair in similar_pairs:
            old = pair["old_location"]
            new = pair["new_location"]

            # Check for different patterns
            if "%2F" in old or "_2F" in new:
                key = "url_encoded"
                patterns.setdefault(key, []).append((old[:70], new[:70]))
            elif len(old.split("/")) != len(new.split("/")):
                key = "path_structure"
                patterns.setdefault(key, []).append((old[:70], new[:70]))
            elif not old.split("/")[-1].count(".") and new.split("/")[-1].count("."):
                key = "missing_extension"
                patterns.setdefault(key, []).append((old[:70], new[:70]))

        for key, examples in patterns.items():
            print(f"\n{key.replace('_', ' ').title()}: {len(examples)} cases")
            for i, (old_ex, new_ex) in enumerate(examples[:3], 1):
                print(f"  {i}. Old: {old_ex}")
                print(f"     New: {new_ex}")
    else:
        print(f"Saved empty file to {output_csv} (no similar pairs found)")


if __name__ == "__main__":
    find_similar_files(
        Path("data/compare_only_old.csv"),
        Path("data/compare_only_new.csv"),
        Path("data/similar.csv"),
        threshold=0.95,
    )
