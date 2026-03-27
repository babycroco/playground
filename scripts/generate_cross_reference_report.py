"""
scripts/generate_cross_reference_report.py

Generate a cross-reference report comparing WP (Wirtschaftsplan) planned values
against actual Hausgeld payments.

Outputs: data/CROSS_REFERENCE_REPORT.xlsx with three tabs:
  - Action Required  (abs(delta_monthly) > 20)
  - Review           (5 <= abs(delta_monthly) <= 20)
  - Correct          (abs(delta_monthly) < 5)

Run with:
    python3 -m scripts.generate_cross_reference_report
"""

import sys
import pandas as pd

BASE_DIR = "/home/user/playground"
INVENTORY_PATH = f"{BASE_DIR}/data/master_inventory.csv"
AUDIT_PATH     = f"{BASE_DIR}/data/audit_report.csv"
PAYMENT_PATH   = f"{BASE_DIR}/data/payment_mori_rapoport.csv"
OUTPUT_PATH    = f"{BASE_DIR}/data/CROSS_REFERENCE_REPORT.xlsx"

# Columns written to every tab
OUTPUT_COLUMNS = [
    "canonical_key",
    "street",
    "unit",
    "wp_total",
    "actual_payment",
    "delta_monthly",
    "delta_annual",
    "match_confidence",
    "category",
]


def load_data():
    inventory = pd.read_csv(INVENTORY_PATH, dtype=str)
    audit     = pd.read_csv(AUDIT_PATH,     dtype=str)
    payments  = pd.read_csv(PAYMENT_PATH,   dtype=str)
    # Convert numeric columns
    for col in ("wp_hausgeld", "wp_ruecklage", "wp_total"):
        audit[col] = pd.to_numeric(audit[col], errors="coerce")
    payments["actual_payment"] = pd.to_numeric(payments["actual_payment"], errors="coerce")
    # Normalise self_payer flag to Python bool
    inventory["self_payer"] = inventory["self_payer"].str.strip().str.lower() == "true"
    return inventory, audit, payments


def match_sources(audit, payments, inventory):
    from audit.unit_matcher import build_match_report

    print("\n--- Matching audit_report against inventory ---")
    # audit_report uses 'street' and 'unit' columns directly
    audit_matched = build_match_report(
        source_df=audit,
        inventory_df=inventory,
        street_col="street",
        unit_col="unit",
    )

    print("\n--- Matching payment file against inventory ---")
    # payment file uses 'Owner_Street' and 'Unit'
    payments_matched = build_match_report(
        source_df=payments,
        inventory_df=inventory,
        street_col="Owner_Street",
        unit_col="Unit",
    )

    return audit_matched, payments_matched


def build_joined(audit_matched, payments_matched, inventory):
    """
    Join audit WP values with actual payments on canonical_key.
    Attach self_payer flag from inventory.
    """
    # Keep only the columns we need from each side
    audit_slim = audit_matched[
        ["canonical_key", "street", "unit", "wp_total", "match_confidence"]
    ].copy()
    audit_slim.rename(columns={"match_confidence": "wp_match_confidence"}, inplace=True)

    payments_slim = payments_matched[
        ["canonical_key", "actual_payment", "match_confidence"]
    ].copy()
    payments_slim.rename(columns={"match_confidence": "pay_match_confidence"}, inplace=True)

    # Inner join — only rows present in both sources
    joined = audit_slim.merge(payments_slim, on="canonical_key", how="inner")

    # Attach self_payer from inventory
    inv_slim = inventory[["canonical_key", "self_payer"]].copy()
    joined = joined.merge(inv_slim, on="canonical_key", how="left")
    joined["self_payer"] = joined["self_payer"].fillna(False)

    # Resolve match_confidence: use the *worse* of the two sides
    # exact > fuzzy > none  =>  none < fuzzy < exact
    confidence_rank = {"exact": 2, "fuzzy": 1, "none": 0}

    def combined_confidence(row):
        r_wp  = confidence_rank.get(row["wp_match_confidence"],  0)
        r_pay = confidence_rank.get(row["pay_match_confidence"], 0)
        return "exact" if min(r_wp, r_pay) == 2 else (
               "fuzzy" if min(r_wp, r_pay) == 1 else "none")

    joined["match_confidence"] = joined.apply(combined_confidence, axis=1)

    return joined


def compute_deltas(df):
    df = df.copy()
    df["delta_monthly"] = df["actual_payment"] - df["wp_total"]
    df["delta_annual"]  = df["delta_monthly"] * 12
    return df


def categorise(df):
    def cat(row):
        adm = abs(row["delta_monthly"])
        if adm < 5:
            return "Correct"
        elif adm <= 20:
            return "Review"
        else:
            return "Action Required"

    df = df.copy()
    df["category"] = df.apply(cat, axis=1)
    return df


def write_excel(df, path):
    tab_order = ["Action Required", "Review", "Correct"]

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for tab_name in tab_order:
            tab_df = df[df["category"] == tab_name][OUTPUT_COLUMNS].copy()
            # Sort by abs(delta_annual) descending
            tab_df = tab_df.reindex(
                tab_df["delta_annual"].abs().sort_values(ascending=False).index
            )
            tab_df.to_excel(writer, sheet_name=tab_name, index=False)

    print(f"\nReport written to: {path}")


def print_summary(df):
    total = len(df)
    matched = (df["match_confidence"] != "none").sum()
    match_rate = matched / total * 100 if total > 0 else 0

    counts = df["category"].value_counts()
    action_count  = counts.get("Action Required", 0)
    review_count  = counts.get("Review",          0)
    correct_count = counts.get("Correct",         0)

    top5 = (
        df[["canonical_key", "street", "unit", "delta_monthly", "delta_annual"]]
        .assign(abs_annual=df["delta_annual"].abs())
        .sort_values("abs_annual", ascending=False)
        .head(5)
        .drop(columns="abs_annual")
    )

    print("\n" + "=" * 60)
    print("  CROSS-REFERENCE REPORT SUMMARY")
    print("=" * 60)
    print(f"  Total units compared : {total}")
    print(f"  Match rate           : {match_rate:.1f}%  ({matched}/{total} matched)")
    print(f"  Action Required      : {action_count}")
    print(f"  Review               : {review_count}")
    print(f"  Correct              : {correct_count}")
    print("\n  Top 5 discrepancies by abs(delta_annual):")
    print(f"  {'canonical_key':<35} {'delta/mo':>9}  {'delta/yr':>9}")
    print(f"  {'-'*35} {'-'*9}  {'-'*9}")
    for _, row in top5.iterrows():
        print(
            f"  {row['canonical_key']:<35} "
            f"{row['delta_monthly']:>+9.2f}  "
            f"{row['delta_annual']:>+9.2f}"
        )
    print("=" * 60 + "\n")


def main():
    print("Loading CSV files...")
    inventory, audit, payments = load_data()

    print(f"  Inventory : {len(inventory)} units "
          f"({inventory['self_payer'].sum()} self-payers)")
    print(f"  Audit     : {len(audit)} rows")
    print(f"  Payments  : {len(payments)} rows")

    audit_matched, payments_matched = match_sources(audit, payments, inventory)

    joined = build_joined(audit_matched, payments_matched, inventory)
    print(f"\nJoined rows before self-payer exclusion: {len(joined)}")

    # Exclude self-payers
    self_payer_keys = joined[joined["self_payer"]]["canonical_key"].tolist()
    if self_payer_keys:
        print(f"Excluding {len(self_payer_keys)} self-payer unit(s): "
              f"{', '.join(self_payer_keys)}")
    joined = joined[~joined["self_payer"]].copy()
    print(f"Rows after self-payer exclusion: {len(joined)}")

    joined = compute_deltas(joined)
    joined = categorise(joined)

    print_summary(joined)
    write_excel(joined, OUTPUT_PATH)

    return 0


if __name__ == "__main__":
    sys.exit(main())
