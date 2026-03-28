"""
scripts/master_audit.py — Main WP audit pipeline

Processes all units in data/managed_portfolio.csv, finds matching
Wirtschaftsplan PDFs in Dropbox, extracts Hausgeld + Rücklage values,
and writes data/audit_report.csv.

Run with:
    python3 -m scripts.master_audit [--dry-run] [--building "Residenzstr. 129"]
"""

import argparse
import csv
import os
import sys

from audit.unit_matcher import normalize_street

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PORTFOLIO_PATH = os.path.join(DATA_DIR, "managed_portfolio.csv")
AUDIT_REPORT_PATH = os.path.join(DATA_DIR, "audit_report.csv")

AUDIT_OUTPUT_COLUMNS = [
    "canonical_key",
    "street",
    "unit_number",
    "status",
    "wp_hausgeld",
    "wp_ruecklage",
    "wp_total",
    "file_year",
    "extraction_method",
]

# ---------------------------------------------------------------------------
# Dropbox helpers
# ---------------------------------------------------------------------------


def find_dropbox_path(
    street: str,
    unit: str,
    dropbox_client,
    folder_cache: dict,
) -> "str | None":
    """
    Locate the WP PDF folder in Dropbox for a given street + unit.

    Strategy:
      1. List '/Apartments/Berlin/' once; cache the result in folder_cache.
      2. Normalize each top-level folder name via normalize_street().
      3. Find the folder whose normalized name matches normalize_street(street).
      4. Inside that folder, look for a WE subfolder matching the unit number.
      5. Return the full Dropbox path, or None if not found.

    Args:
        street:         Raw or normalized street name.
        unit:           Normalized unit number (e.g. "15").
        dropbox_client: An authenticated Dropbox SDK client (dropbox.Dropbox).
        folder_cache:   Shared dict used to cache the top-level listing.

    Returns:
        Full Dropbox path string (e.g. '/Apartments/Berlin/Residenzstr_129/WE15')
        or None if no match is found.
    """
    if dropbox_client is None:
        return None

    base_path = "/Apartments/Berlin"

    # 1. List top-level folders once and cache
    if "top_level" not in folder_cache:
        try:
            result = dropbox_client.files_list_folder(base_path)
            folder_cache["top_level"] = [
                entry.name for entry in result.entries
                if hasattr(entry, "path_lower")  # folders and files both have this
            ]
        except Exception as exc:
            print(f"  [WARN] Could not list Dropbox folder {base_path}: {exc}",
                  file=sys.stderr)
            folder_cache["top_level"] = []

    top_folders = folder_cache.get("top_level", [])

    # 2. Normalize and match street
    norm_target = normalize_street(street)
    matched_folder = None
    for folder_name in top_folders:
        if normalize_street(folder_name) == norm_target:
            matched_folder = folder_name
            break

    if matched_folder is None:
        return None

    building_path = f"{base_path}/{matched_folder}"

    # 3. Look for WE subfolder
    we_folder_key = f"we_{building_path}"
    if we_folder_key not in folder_cache:
        try:
            result = dropbox_client.files_list_folder(building_path)
            folder_cache[we_folder_key] = [
                entry.name for entry in result.entries
            ]
        except Exception as exc:
            print(
                f"  [WARN] Could not list Dropbox folder {building_path}: {exc}",
                file=sys.stderr,
            )
            folder_cache[we_folder_key] = []

    we_folders = folder_cache.get(we_folder_key, [])

    # Match unit (normalize both sides: strip leading zeros, WE prefix etc.)
    from audit.unit_matcher import normalize_unit
    norm_unit = normalize_unit(unit)
    for we_name in we_folders:
        if normalize_unit(we_name) == norm_unit:
            return f"{building_path}/{we_name}"

    return None


# ---------------------------------------------------------------------------
# Unit processor
# ---------------------------------------------------------------------------


def process_unit(
    row: dict,
    dropbox_client,
    folder_cache: dict,
    dry_run: bool = False,
) -> dict:
    """
    Process one managed_portfolio row against Dropbox.

    Args:
        row:            Dict from managed_portfolio.csv.
        dropbox_client: Authenticated Dropbox client, or None.
        folder_cache:   Shared folder listing cache.
        dry_run:        If True, return a mock result without hitting Dropbox.

    Returns:
        Dict with keys matching AUDIT_OUTPUT_COLUMNS.
    """
    canonical_key = row.get("canonical_key", "")
    street = row.get("street", "")
    unit_number = row.get("unit_number", "")

    # Always skip direct payers
    if str(row.get("is_direct_payer", "")).lower() in ("true", "1", "yes"):
        return {
            "canonical_key": canonical_key,
            "street": street,
            "unit_number": unit_number,
            "status": "Skipped - Direct Payer",
            "wp_hausgeld": "",
            "wp_ruecklage": "",
            "wp_total": "",
            "file_year": "",
            "extraction_method": "",
        }

    # Dry-run: return mock result
    if dry_run:
        latest_hg = row.get("latest_hg", "")
        latest_year = row.get("latest_hg_year", "")
        return {
            "canonical_key": canonical_key,
            "street": street,
            "unit_number": unit_number,
            "status": "Dry Run",
            "wp_hausgeld": latest_hg,
            "wp_ruecklage": "",
            "wp_total": latest_hg,
            "file_year": latest_year,
            "extraction_method": "dry_run_mock",
        }

    # Live run: attempt Dropbox lookup
    dropbox_path = find_dropbox_path(street, unit_number, dropbox_client, folder_cache)

    if dropbox_path is None:
        return {
            "canonical_key": canonical_key,
            "street": street,
            "unit_number": unit_number,
            "status": "Download Failed",
            "wp_hausgeld": "",
            "wp_ruecklage": "",
            "wp_total": "",
            "file_year": "",
            "extraction_method": "",
        }

    # TODO: Download PDF from dropbox_path and extract HG/Rücklage values
    # For now return a placeholder success result
    return {
        "canonical_key": canonical_key,
        "street": street,
        "unit_number": unit_number,
        "status": "Found",
        "wp_hausgeld": "",
        "wp_ruecklage": "",
        "wp_total": "",
        "file_year": "",
        "extraction_method": "dropbox_pdf",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Master WP audit pipeline — matches managed units to Dropbox PDFs."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without hitting Dropbox; use mock results.",
    )
    parser.add_argument(
        "--building",
        type=str,
        default=None,
        help='Filter to a single building, e.g. "Residenzstr. 129".',
    )
    args = parser.parse_args()

    # Load managed portfolio
    if not os.path.exists(PORTFOLIO_PATH):
        print(f"ERROR: managed_portfolio.csv not found at {PORTFOLIO_PATH}", file=sys.stderr)
        print("Run: python3 -m scripts.build_managed_portfolio", file=sys.stderr)
        sys.exit(1)

    with open(PORTFOLIO_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        portfolio = list(reader)

    # Filter direct payers (they'll be logged as Skipped)
    active_rows = [
        r for r in portfolio
        if str(r.get("is_direct_payer", "")).lower() not in ("true", "1", "yes")
    ]

    # Optional building filter
    if args.building:
        norm_filter = normalize_street(args.building)
        active_rows = [
            r for r in active_rows
            if normalize_street(r.get("street", "")) == norm_filter
        ]
        print(f"Filtering to building: {args.building!r} ({len(active_rows)} units)")

    # Initialize Dropbox client (gracefully handle missing credentials)
    dropbox_client = None
    if not args.dry_run:
        try:
            import dropbox  # type: ignore
            token = os.environ.get("DROPBOX_ACCESS_TOKEN", "")
            if token:
                dropbox_client = dropbox.Dropbox(token)
                print("Dropbox client initialized.")
            else:
                print(
                    "[WARN] DROPBOX_ACCESS_TOKEN not set — running in degraded mode "
                    "(all units will fail lookup). Use --dry-run for mock results.",
                    file=sys.stderr,
                )
        except ImportError:
            print(
                "[WARN] dropbox package not installed — running in degraded mode. "
                "Install with: pip install dropbox",
                file=sys.stderr,
            )

    folder_cache: dict = {}
    results = []
    count_found = 0
    count_failed = 0
    count_skipped = 0

    for row in portfolio:
        result = process_unit(row, dropbox_client, folder_cache, dry_run=args.dry_run)
        results.append(result)
        status = result.get("status", "")
        if "Skipped" in status:
            count_skipped += 1
        elif status in ("Found", "Dry Run"):
            count_found += 1
        else:
            count_failed += 1

    # Write audit report
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(AUDIT_REPORT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=AUDIT_OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(results)

    total_processed = len(results)
    print(f"\nAudit complete: {total_processed} processed, "
          f"{count_found} found, {count_failed} failed, {count_skipped} skipped")
    print(f"Output: {AUDIT_REPORT_PATH}")


if __name__ == "__main__":
    main()

# TODO: After audit complete, sync updated HG values to
# data/portfolio January 2024 NEW.xlsx via scripts/sync_portfolio.py
