"""
scripts/vision_audit.py — Gemini Vision fallback for failed WP extractions

For units in managed_portfolio.csv that have status="Download Failed" in
audit_report.csv, attempt extraction using Google Gemini Vision API.

Only processes units that exist in managed_portfolio.csv.

Run with:
    python3 -m scripts.vision_audit [--dry-run]
"""

import argparse
import csv
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PORTFOLIO_PATH = os.path.join(DATA_DIR, "managed_portfolio.csv")
AUDIT_REPORT_PATH = os.path.join(DATA_DIR, "audit_report.csv")


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def load_failed_units() -> list[dict]:
    """
    Join managed_portfolio.csv with audit_report.csv.

    Returns rows where:
      - status == "Download Failed"  (from audit_report.csv)
      - AND the unit's canonical_key exists in managed_portfolio.csv

    If audit_report.csv does not exist yet, prints a warning and returns [].
    """
    # Load managed portfolio
    if not os.path.exists(PORTFOLIO_PATH):
        print(
            f"ERROR: managed_portfolio.csv not found at {PORTFOLIO_PATH}",
            file=sys.stderr,
        )
        print("Run: python3 -m scripts.build_managed_portfolio", file=sys.stderr)
        return []

    with open(PORTFOLIO_PATH, newline="", encoding="utf-8") as f:
        portfolio_rows = list(csv.DictReader(f))

    managed_keys = {r["canonical_key"] for r in portfolio_rows if r.get("canonical_key")}
    portfolio_by_key = {r["canonical_key"]: r for r in portfolio_rows if r.get("canonical_key")}

    # Load audit report
    if not os.path.exists(AUDIT_REPORT_PATH):
        print(
            f"[WARN] audit_report.csv not found at {AUDIT_REPORT_PATH}. "
            "Run: python3 -m scripts.master_audit",
            file=sys.stderr,
        )
        return []

    with open(AUDIT_REPORT_PATH, newline="", encoding="utf-8") as f:
        audit_rows = list(csv.DictReader(f))

    # Filter: Download Failed AND in managed portfolio
    failed_units = []
    for audit_row in audit_rows:
        if audit_row.get("status") != "Download Failed":
            continue
        key = audit_row.get("canonical_key", "")
        if key not in managed_keys:
            continue  # Not in managed portfolio — skip

        # Merge: start from portfolio row, overlay audit fields
        merged = dict(portfolio_by_key[key])
        merged.update(audit_row)
        failed_units.append(merged)

    return failed_units


# ---------------------------------------------------------------------------
# Vision processor (stub)
# ---------------------------------------------------------------------------


def process_with_vision(row: dict, dry_run: bool = False) -> dict:
    """
    Attempt to extract WP data for one unit using Google Gemini Vision API.

    This is a stub implementation. Full logic will:
      1. Download the PDF from Dropbox (or a fallback path).
      2. Convert the relevant page(s) to image(s).
      3. Send image(s) to Gemini Vision with a structured extraction prompt.
      4. Parse the response to extract Hausgeld + Rücklage values.
      5. Return structured result dict.

    Args:
        row:      Merged row from managed_portfolio + audit_report.
        dry_run:  If True, print what it would do without calling the API.

    Returns:
        Dict with keys: canonical_key, street, unit_number, status,
                        wp_hausgeld, wp_ruecklage, wp_total, file_year,
                        extraction_method.
    """
    canonical_key = row.get("canonical_key", "")
    street = row.get("street", "")
    unit_number = row.get("unit_number", "")

    if dry_run:
        print(
            f"  [DRY RUN] Would call Gemini Vision for "
            f"{canonical_key} ({street} WE{unit_number})"
        )
        return {
            "canonical_key": canonical_key,
            "street": street,
            "unit_number": unit_number,
            "status": "Dry Run - Vision",
            "wp_hausgeld": "",
            "wp_ruecklage": "",
            "wp_total": "",
            "file_year": "",
            "extraction_method": "gemini_vision_dry_run",
        }

    # TODO: Implement live Gemini Vision extraction
    # import google.generativeai as genai
    # genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    # model = genai.GenerativeModel("gemini-1.5-pro-vision")
    # ... upload image, parse response ...

    print(
        f"  [STUB] Vision extraction not yet implemented for {canonical_key}",
        file=sys.stderr,
    )
    return {
        "canonical_key": canonical_key,
        "street": street,
        "unit_number": unit_number,
        "status": "Vision Not Implemented",
        "wp_hausgeld": "",
        "wp_ruecklage": "",
        "wp_total": "",
        "file_year": "",
        "extraction_method": "gemini_vision_stub",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Gemini Vision fallback — retries WP extraction for units "
            "that failed in the main Dropbox audit pipeline."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be processed without calling the Gemini API.",
    )
    args = parser.parse_args()

    failed_units = load_failed_units()

    print(
        f"{len(failed_units)} units eligible for vision retry "
        f"(in managed portfolio with Download Failed status)"
    )

    if not failed_units:
        print("Nothing to do.")
        return

    if args.dry_run:
        print("\n[DRY RUN] Would process the following units with Gemini Vision:")

    for row in failed_units:
        process_with_vision(row, dry_run=args.dry_run)

    if not args.dry_run:
        print(
            "\nNote: Live Gemini Vision extraction is not yet implemented. "
            "Use --dry-run to preview eligible units."
        )


if __name__ == "__main__":
    main()
