"""
scripts/generate_cross_reference_report.py

Generate a cross-reference report comparing WP (Wirtschaftsplan) planned values
against actual Hausgeld payments.

Input files:
  - data/audit_report_normalized.csv  — WP planned values, pre-normalized
  - data/payment_mori_rapoport.csv    — actual payments
  - data/master_inventory.csv         — reference inventory with self_payer flag

Output: data/CROSS_REFERENCE_REPORT.xlsx with three tabs:
  - Action Required  (abs(delta_monthly) > 20)
  - Review           (5 <= abs(delta_monthly) <= 20)
  - Correct          (abs(delta_monthly) < 5)

Run with:
    python3 -m scripts.generate_cross_reference_report
"""

import sys
import re
import pandas as pd

BASE_DIR       = "/home/user/playground"
INVENTORY_PATH = f"{BASE_DIR}/data/master_inventory.csv"
AUDIT_PATH     = f"{BASE_DIR}/data/audit_report_normalized.csv"
PAYMENT_PATH   = f"{BASE_DIR}/data/payment_mori_rapoport.csv"
OUTPUT_PATH    = f"{BASE_DIR}/data/CROSS_REFERENCE_REPORT.xlsx"

# Ordered columns written to every tab
OUTPUT_COLUMNS = [
    "canonical_key",
    "street",
    "unit",
    "wp_hausgeld",
    "wp_ruecklage",
    "wp_total",
    "actual_payment",
    "delta_monthly",
    "delta_annual",
    "match_confidence",
    "category",
]

# Confidence ranking: higher = better
_CONFIDENCE_RANK = {"exact": 2, "fuzzy": 1, "none": 0}
_RANK_TO_LABEL   = {2: "exact", 1: "fuzzy", 0: "none"}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data():
    """Read all three source CSVs and coerce types."""
    inventory = pd.read_csv(INVENTORY_PATH, dtype=str)
    audit     = pd.read_csv(AUDIT_PATH,     dtype=str)
    payments  = pd.read_csv(PAYMENT_PATH,   dtype=str)

    # Coerce numeric WP columns
    for col in ("wp_hausgeld", "wp_ruecklage", "wp_total"):
        audit[col] = pd.to_numeric(audit[col], errors="coerce")

    payments["actual_payment"] = pd.to_numeric(payments["actual_payment"], errors="coerce")

    # Normalise self_payer flag to Python bool
    inventory["self_payer"] = inventory["self_payer"].str.strip().str.lower() == "true"

    return inventory, audit, payments


# ---------------------------------------------------------------------------
# Payment matching via unit_matcher
# ---------------------------------------------------------------------------

def match_payments(payments: pd.DataFrame, inventory: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize the payment file against inventory using build_match_report.
    Returns the enriched payments DataFrame with matched_inventory_unit_id.
    """
    from audit.unit_matcher import build_match_report

    print("\n--- Matching payment file against inventory ---")
    return build_match_report(
        source_df=payments,
        inventory_df=inventory,
        street_col="Owner_Street",
        unit_col="Unit",
    )


# ---------------------------------------------------------------------------
# Derive a true unit number from audit unit_path / unit column
# ---------------------------------------------------------------------------

def _extract_unit_number(unit_str: str) -> str:
    """
    Strip 'WE' prefix (and leading zeros) from an audit unit string and return
    the bare integer string so it can be compared with inventory unit numbers.

    Examples:
      "WE15"   -> "15"
      "WE 06"  -> "6"       (strips leading zero)
      "WE 3"   -> "3"
      "WE 28"  -> "28"
    """
    if not unit_str or not isinstance(unit_str, str):
        return ""
    s = re.sub(r"^WE\s*", "", unit_str.strip(), flags=re.IGNORECASE)
    # Remove leading zeros for integer comparison
    try:
        return str(int(s))
    except ValueError:
        return s.strip()


# ---------------------------------------------------------------------------
# Build the audit lookup keyed by (normalized_street, unit_number)
# ---------------------------------------------------------------------------

def _build_audit_lookup(audit: pd.DataFrame) -> dict:
    """
    Return a dict keyed by (inventory_unit_number_str, street_normalized) ->
    audit row dict.

    The audit CSV 'unit' column contains values like "WE15", "WE 06", "WE 28".
    We strip the WE prefix and normalise street with normalize_street so we can
    match against inventory rows.
    """
    from audit.unit_matcher import normalize_street

    lookup = {}
    for _, row in audit.iterrows():
        unit_num = _extract_unit_number(str(row.get("unit", "")))
        norm_st  = normalize_street(str(row.get("street", "")))
        if unit_num and norm_st:
            key = (norm_st, unit_num)
            # In case of duplicates keep the first occurrence
            if key not in lookup:
                lookup[key] = row.to_dict()
    return lookup


# ---------------------------------------------------------------------------
# Join: payments (matched to inventory) <-> audit lookup
# ---------------------------------------------------------------------------

def build_joined(
    audit: pd.DataFrame,
    payments_matched: pd.DataFrame,
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    """
    For every payment row that was successfully matched to an inventory unit,
    look up the corresponding audit (WP) row using street + unit number.
    Attach self_payer from inventory.

    match_confidence is the *worse* of audit-side (wp_match_confidence) and
    payment-side (pay_match_confidence) to reflect total join uncertainty.

    Returns a merged DataFrame with all needed columns plus:
      - self_payer          (bool)
      - wp_match_confidence / pay_match_confidence (for internal use)
      - match_confidence    (combined, worst-of-two)
    """
    from audit.unit_matcher import normalize_street

    # --- Enrich inventory with normalised street + bare unit number ---------
    inv = inventory.copy()
    inv["_norm_street"] = inv["street"].apply(normalize_street)
    inv["_unit_num"]    = inv["unit"].apply(
        lambda u: str(int(u)) if str(u).isdigit() else str(u).strip()
    )

    # Build audit lookup: (norm_street, unit_num) -> audit row
    audit_lookup = _build_audit_lookup(audit)

    records = []

    for _, pay_row in payments_matched.iterrows():
        pay_inv_id   = str(pay_row.get("matched_inventory_unit_id", "")).strip()
        pay_conf     = str(pay_row.get("match_confidence", "none")).strip()
        actual_pay   = pay_row.get("actual_payment")

        if not pay_inv_id:
            # Payment could not be matched to inventory at all — skip
            continue

        # Find the inventory row for this payment
        inv_rows = inv[inv["canonical_key"] == pay_inv_id]
        if inv_rows.empty:
            continue
        inv_row = inv_rows.iloc[0]

        norm_street = inv_row["_norm_street"]
        unit_num    = inv_row["_unit_num"]

        # Look up the audit WP row by (street, unit number)
        audit_row = audit_lookup.get((norm_street, unit_num))
        if audit_row is None:
            # No WP data found for this unit — skip
            continue

        wp_conf = str(audit_row.get("match_confidence", "none")).strip()

        # Combined confidence = worst of both sides
        combined_rank = min(
            _CONFIDENCE_RANK.get(wp_conf,  0),
            _CONFIDENCE_RANK.get(pay_conf, 0),
        )
        combined_conf = _RANK_TO_LABEL[combined_rank]

        records.append({
            "canonical_key"    : audit_row.get("canonical_key", ""),
            "street"           : audit_row.get("street",        ""),
            "unit"             : audit_row.get("unit",          ""),
            "wp_hausgeld"      : audit_row.get("wp_hausgeld"),
            "wp_ruecklage"     : audit_row.get("wp_ruecklage"),
            "wp_total"         : audit_row.get("wp_total"),
            "actual_payment"   : actual_pay,
            "self_payer"       : bool(inv_row.get("self_payer", False)),
            "match_confidence" : combined_conf,
            # Keep individual confidences for debugging if needed
            "wp_match_confidence"  : wp_conf,
            "pay_match_confidence" : pay_conf,
            # Inventory canonical key (needed for self-payer cross-check)
            "_inv_canonical_key"   : pay_inv_id,
        })

    joined = pd.DataFrame(records)

    # Safety: also flag via inventory self_payer using the inventory canonical key
    # (in case the audit lookup resolved to a different row)
    self_payer_set = set(inventory.loc[inventory["self_payer"], "canonical_key"])
    if not joined.empty:
        joined["self_payer"] = (
            joined["self_payer"]
            | joined["_inv_canonical_key"].isin(self_payer_set)
        )

    return joined


# ---------------------------------------------------------------------------
# Delta computation & categorisation
# ---------------------------------------------------------------------------

def compute_deltas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["delta_monthly"] = df["actual_payment"] - df["wp_total"]
    df["delta_annual"]  = df["delta_monthly"] * 12
    return df


def categorise(df: pd.DataFrame) -> pd.DataFrame:
    def _cat(adm: float) -> str:
        if adm < 5:
            return "Correct"
        elif adm <= 20:
            return "Review"
        else:
            return "Action Required"

    df = df.copy()
    df["category"] = df["delta_monthly"].abs().apply(_cat)
    return df


# ---------------------------------------------------------------------------
# Excel output
# ---------------------------------------------------------------------------

def write_excel(df: pd.DataFrame, path: str) -> None:
    tab_order = ["Action Required", "Review", "Correct"]

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for tab_name in tab_order:
            tab_df = (
                df[df["category"] == tab_name][OUTPUT_COLUMNS]
                .copy()
                .sort_values("delta_annual", key=lambda s: s.abs(), ascending=False)
                .reset_index(drop=True)
            )
            tab_df.to_excel(writer, sheet_name=tab_name, index=False)

    print(f"\nReport written to: {path}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(
    df_before_exclusion: pd.DataFrame,
    df: pd.DataFrame,
    excluded_rows: pd.DataFrame,
) -> None:
    """Print full summary: totals, exclusions, match rate, per-category counts, top 5."""
    total_before  = len(df_before_exclusion)
    n_excluded    = len(excluded_rows)
    total         = len(df)
    matched       = (df["match_confidence"] != "none").sum()
    match_rate    = matched / total * 100 if total > 0 else 0.0

    counts        = df["category"].value_counts()
    action_count  = counts.get("Action Required", 0)
    review_count  = counts.get("Review",          0)
    correct_count = counts.get("Correct",         0)

    top5 = (
        df[["canonical_key", "street", "unit", "delta_monthly", "delta_annual"]]
        .assign(_abs_annual=df["delta_annual"].abs())
        .sort_values("_abs_annual", ascending=False)
        .head(5)
        .drop(columns="_abs_annual")
    )

    # Self-payer unit identifiers for display
    if not excluded_rows.empty and "canonical_key" in excluded_rows.columns:
        excl_keys = excluded_rows["canonical_key"].tolist()
    else:
        excl_keys = []

    print("\n" + "=" * 65)
    print("  CROSS-REFERENCE REPORT SUMMARY")
    print("=" * 65)
    print(f"  Total rows joined        : {total_before}")
    if excl_keys:
        print(
            f"  Self-payers excluded     : {n_excluded}"
            f"  ({', '.join(excl_keys)})"
        )
    else:
        print(f"  Self-payers excluded     : {n_excluded}")
    print(f"  Rows after exclusion     : {total}")
    print(f"  Match rate               : {match_rate:.1f}%  ({matched}/{total} matched)")
    print(f"  ---")
    print(f"  Action Required          : {action_count}")
    print(f"  Review                   : {review_count}")
    print(f"  Correct                  : {correct_count}")
    print(f"\n  Top 5 discrepancies by abs(delta_annual):")
    print(f"  {'canonical_key':<35} {'delta/mo':>9}  {'delta/yr':>10}")
    print(f"  {'-'*35} {'-'*9}  {'-'*10}")
    for _, row in top5.iterrows():
        print(
            f"  {row['canonical_key']:<35} "
            f"{row['delta_monthly']:>+9.2f}  "
            f"{row['delta_annual']:>+10.2f}"
        )
    print("=" * 65 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print("Loading CSV files...")
    inventory, audit, payments = load_data()

    self_payer_count = int(inventory["self_payer"].sum())
    print(f"  Inventory : {len(inventory)} units ({self_payer_count} self-payers in inventory)")
    print(f"  Audit     : {len(audit)} rows  (pre-normalized, with matched_inventory_unit_id)")
    print(f"  Payments  : {len(payments)} rows")

    # Step 2: normalize payment file against inventory
    payments_matched = match_payments(payments, inventory)

    # Steps 3 & 4: join audit + payments via (street, unit_number) lookup,
    #              attach self_payer from inventory
    joined = build_joined(audit, payments_matched, inventory)
    print(f"\nJoined rows before self-payer exclusion: {len(joined)}")

    if joined.empty:
        print("ERROR: No rows were joined. Check street/unit normalization.")
        return 1

    # Step 5: exclude self-payers
    self_payer_mask = joined["self_payer"].astype(bool)
    excluded_rows   = joined[self_payer_mask].copy()
    if not excluded_rows.empty:
        excl_display = excluded_rows["canonical_key"].tolist()
        print(
            f"Excluding {len(excluded_rows)} self-payer unit(s): "
            f"{', '.join(excl_display)}"
        )
    df_before = joined.copy()
    joined    = joined[~self_payer_mask].copy().reset_index(drop=True)
    print(f"Rows after self-payer exclusion: {len(joined)}")

    # Steps 6 & 7: compute deltas and categorise
    joined = compute_deltas(joined)
    joined = categorise(joined)

    # Step 9: print summary (before Step 8 so summary appears in terminal before file write)
    print_summary(df_before, joined, excluded_rows)

    # Step 8: write Excel
    write_excel(joined, OUTPUT_PATH)

    return 0


if __name__ == "__main__":
    sys.exit(main())
