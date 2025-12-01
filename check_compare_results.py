#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check compare results and track row counts to ensure they decrease after fixes."""
import csv
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

COMPARE_RESULTS_FILE = Path("data/.compare_results.json")
COMPARE_ONLY_NEW = Path("data/compare_only_new.csv")
COMPARE_ONLY_OLD = Path("data/compare_only_old.csv")


def get_row_counts() -> dict:
    """Get current row counts from compare output files."""
    counts = {"new_only": 0, "old_only": 0}
    
    if COMPARE_ONLY_NEW.exists():
        with open(COMPARE_ONLY_NEW, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            counts["new_only"] = sum(1 for _ in reader)
    
    if COMPARE_ONLY_OLD.exists():
        with open(COMPARE_ONLY_OLD, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            counts["old_only"] = sum(1 for _ in reader)
    
    return counts


def load_previous_counts() -> dict:
    """Load previous row counts from stored file."""
    if COMPARE_RESULTS_FILE.exists():
        try:
            with open(COMPARE_RESULTS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_counts(counts: dict) -> None:
    """Save current row counts to file."""
    COMPARE_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COMPARE_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(counts, f, indent=2)


def check_compare_results() -> bool:
    """Check if current compare results show improvement (fewer rows)."""
    current_counts = get_row_counts()
    previous_counts = load_previous_counts()
    
    print("=" * 60)
    print("Compare Results Check")
    print("=" * 60)
    
    if not previous_counts:
        print("No previous results found. Storing current counts as baseline.")
        print(f"  New-only rows: {current_counts['new_only']}")
        print(f"  Old-only rows: {current_counts['old_only']}")
        save_counts(current_counts)
        return True
    
    print("Previous results:")
    print(f"  New-only rows: {previous_counts.get('new_only', 0)}")
    print(f"  Old-only rows: {previous_counts.get('old_only', 0)}")
    print()
    print("Current results:")
    print(f"  New-only rows: {current_counts['new_only']}")
    print(f"  Old-only rows: {current_counts['old_only']}")
    print()
    
    # Check if counts decreased
    new_decreased = current_counts["new_only"] < previous_counts.get("new_only", float("inf"))
    old_decreased = current_counts["old_only"] < previous_counts.get("old_only", float("inf"))
    
    if new_decreased and old_decreased:
        print("✓ SUCCESS: Both row counts decreased!")
        print("  This indicates normalization improvements are working.")
    elif new_decreased:
        print("⚠ PARTIAL: New-only rows decreased, but old-only rows increased.")
    elif old_decreased:
        print("⚠ PARTIAL: Old-only rows decreased, but new-only rows increased.")
    else:
        print("✗ WARNING: Row counts did not decrease.")
        if current_counts["new_only"] > previous_counts.get("new_only", 0):
            print(f"  New-only increased by {current_counts['new_only'] - previous_counts.get('new_only', 0)}")
        if current_counts["old_only"] > previous_counts.get("old_only", 0):
            print(f"  Old-only increased by {current_counts['old_only'] - previous_counts.get('old_only', 0)}")
        print("  This may indicate new normalization issues were introduced.")
    
    print()
    print("Updating stored counts...")
    save_counts(current_counts)
    print("=" * 60)
    
    return new_decreased and old_decreased


if __name__ == "__main__":
    success = check_compare_results()
    sys.exit(0 if success else 1)

