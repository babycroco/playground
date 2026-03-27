"""
scripts/normalize_audit_report.py

Normalize all unit IDs in data/audit_report.csv using audit/unit_matcher.py
and save the enriched file to data/audit_report_normalized.csv.

Run with:
    python3 -m scripts.normalize_audit_report
"""

import pathlib
import pandas as pd
from audit.unit_matcher import build_match_report

# ---------------------------------------------------------------------------
# Paths (absolute, derived from this file's location)
# ---------------------------------------------------------------------------
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
AUDIT_REPORT_PATH = BASE_DIR / "data" / "audit_report.csv"
MASTER_INVENTORY_PATH = BASE_DIR / "data" / "master_inventory.csv"
OUTPUT_PATH = BASE_DIR / "data" / "audit_report_normalized.csv"


def main() -> None:
    # 1. Load source data
    audit_df = pd.read_csv(AUDIT_REPORT_PATH)
    print(f"Loaded audit report:     {len(audit_df)} rows  ({AUDIT_REPORT_PATH})")

    # 2. Load reference inventory
    inventory_df = pd.read_csv(MASTER_INVENTORY_PATH)
    print(f"Loaded master inventory: {len(inventory_df)} rows  ({MASTER_INVENTORY_PATH})")

    # 3. Run batch matching — adds canonical_key, match_confidence,
    #    matched_inventory_unit_id columns to audit_df
    enriched_df = build_match_report(
        audit_df,
        inventory_df,
        street_col="street",
        unit_col="unit",
    )

    # 4. Save enriched DataFrame
    enriched_df.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved normalized report: {OUTPUT_PATH}")

    # 5. Print final match counts
    counts = enriched_df["match_confidence"].value_counts()
    exact = int(counts.get("exact", 0))
    fuzzy = int(counts.get("fuzzy", 0))
    unmatched = int(counts.get("none", 0))
    total = len(enriched_df)

    print("\nFinal match counts:")
    print(f"  Exact:     {exact}")
    print(f"  Fuzzy:     {fuzzy}")
    print(f"  Unmatched: {unmatched}")
    print(f"  Total:     {total}")


if __name__ == "__main__":
    main()
