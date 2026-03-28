"""
scripts/generate_cross_reference_report.py

Cross-reference report comparing:
  - What you SHOULD pay → Wirtschaftsplan extracted value (audit_report.csv)
  - What you ACTUALLY pay → managed_portfolio.csv latest_hg (from Rental_Payments-NEW.xlsx)

Both sides share canonical_key — no fuzzy matching needed.
Direct payers (is_direct_payer=True) are excluded.

Input files:
  - data/managed_portfolio.csv  — 243 managed units, HG by year, flags
  - data/audit_report.csv       — WP extracted values per unit

Output: data/CROSS_REFERENCE_REPORT.xlsx with three tabs:
  - Action Required  (abs(delta_vs_latest) > 20)
  - Review           (5 <= abs(delta_vs_latest) <= 20)
  - Correct          (abs(delta_vs_latest) < 5)

Run with:
    python3 -m scripts.generate_cross_reference_report
"""

import os
import sys
import datetime as _dt

import pandas as pd

BASE_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTFOLIO_PATH  = os.path.join(BASE_DIR, "data", "managed_portfolio.csv")
AUDIT_PATH      = os.path.join(BASE_DIR, "data", "audit_report.csv")
OUTPUT_PATH     = os.path.join(BASE_DIR, "data", "CROSS_REFERENCE_REPORT.xlsx")

OUTPUT_COLUMNS = [
    "canonical_key",
    "owner",
    "street",
    "unit_number",
    "hg_2024",
    "hg_2025",
    "hg_2026",
    "latest_hg",
    "latest_hg_year",
    "hg_wp_extracted",
    "delta_vs_2026",
    "delta_vs_latest",
    "needs_wp_update",
    "category",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load managed_portfolio and audit_report, coerce numeric columns."""

    portfolio = pd.read_csv(PORTFOLIO_PATH, dtype=str)
    portfolio.columns = [c.strip().lower().replace(" ", "_")
                         for c in portfolio.columns]

    for col in ("hg_2024", "hg_2025", "hg_2026", "latest_hg"):
        if col in portfolio.columns:
            portfolio[col] = pd.to_numeric(portfolio[col], errors="coerce")

    # Boolean flag columns
    for flag in ("is_direct_payer", "needs_wp_update"):
        if flag in portfolio.columns:
            portfolio[flag] = portfolio[flag].str.strip().str.lower() == "true"

    audit = pd.read_csv(AUDIT_PATH, dtype=str)
    audit.columns = [c.strip().lower().replace(" ", "_") for c in audit.columns]

    for col in ("wp_hausgeld", "wp_ruecklage", "wp_total"):
        if col in audit.columns:
            audit[col] = pd.to_numeric(audit[col], errors="coerce")

    return portfolio, audit


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------

def build_joined(portfolio: pd.DataFrame, audit: pd.DataFrame) -> pd.DataFrame:
    """
    Inner-join portfolio (payments) with audit (WP extractions) on canonical_key.
    Exclude direct payers. Add hg_wp_extracted and delta columns.
    """
    # Keep only useful audit columns
    audit_slim = audit[
        [c for c in ("canonical_key", "wp_hausgeld", "wp_ruecklage", "wp_total",
                     "status", "file_year", "extraction_method")
         if c in audit.columns]
    ].copy()
    audit_slim.rename(columns={"wp_total": "hg_wp_extracted"}, inplace=True)

    joined = portfolio.merge(audit_slim, on="canonical_key", how="left")

    # Exclude direct payers
    if "is_direct_payer" in joined.columns:
        joined = joined[~joined["is_direct_payer"]].copy()

    return joined.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Delta computation & categorisation
# ---------------------------------------------------------------------------

def compute_deltas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    hg_wp = pd.to_numeric(df.get("hg_wp_extracted"), errors="coerce")

    if "hg_2026" in df.columns:
        df["delta_vs_2026"] = hg_wp - pd.to_numeric(df["hg_2026"], errors="coerce")
    else:
        df["delta_vs_2026"] = float("nan")

    if "latest_hg" in df.columns:
        df["delta_vs_latest"] = hg_wp - pd.to_numeric(df["latest_hg"], errors="coerce")
    else:
        df["delta_vs_latest"] = float("nan")

    return df


def categorise(df: pd.DataFrame) -> pd.DataFrame:
    def _cat(delta: float) -> str:
        if pd.isna(delta):
            return "No WP Data"
        adm = abs(delta)
        if adm < 5:
            return "Correct"
        elif adm <= 20:
            return "Review"
        else:
            return "Action Required"

    df = df.copy()
    df["category"] = df["delta_vs_latest"].apply(_cat)
    return df


# ---------------------------------------------------------------------------
# Excel output
# ---------------------------------------------------------------------------

def write_excel(df: pd.DataFrame, path: str) -> None:
    tab_order = ["Action Required", "Review", "Correct", "No WP Data"]

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for tab_name in tab_order:
            tab_df = df[df["category"] == tab_name].copy()
            if tab_df.empty:
                continue
            # Sort by abs(delta_vs_latest) descending; NaN last
            sort_key = tab_df["delta_vs_latest"].abs() if tab_name != "No WP Data" \
                       else pd.Series(range(len(tab_df)), index=tab_df.index)
            tab_df = (
                tab_df
                .assign(_sort=sort_key)
                .sort_values("_sort", ascending=False, na_position="last")
                .drop(columns="_sort")
                [[c for c in OUTPUT_COLUMNS if c in tab_df.columns]]
                .reset_index(drop=True)
            )
            tab_df.to_excel(writer, sheet_name=tab_name, index=False)

    print(f"\nReport written to: {path}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame, n_direct_payers: int) -> None:
    total       = len(df)
    counts      = df["category"].value_counts()
    action_cnt  = counts.get("Action Required", 0)
    review_cnt  = counts.get("Review",          0)
    correct_cnt = counts.get("Correct",         0)
    nowp_cnt    = counts.get("No WP Data",      0)

    has_wp   = df["hg_wp_extracted"].notna().sum()
    has_2026 = df["hg_2026"].notna().sum() if "hg_2026" in df.columns else 0

    top5 = (
        df[df["delta_vs_latest"].notna()]
        [["canonical_key", "owner", "delta_vs_latest"]]
        .assign(_abs=df["delta_vs_latest"].abs())
        .sort_values("_abs", ascending=False)
        .head(5)
        .drop(columns="_abs")
    )

    print("\n" + "=" * 65)
    print("  CROSS-REFERENCE REPORT SUMMARY")
    print("=" * 65)
    print(f"  Managed units (portfolio):  {total + n_direct_payers}")
    print(f"  Direct payers excluded:     {n_direct_payers}")
    print(f"  Units compared:             {total}")
    print(f"  With WP extracted:          {has_wp}")
    print(f"  With 2026 HG:               {has_2026}")
    print(f"  ---")
    print(f"  Action Required (>€20/mo):  {action_cnt}")
    print(f"  Review (€5–20/mo):          {review_cnt}")
    print(f"  Correct (<€5/mo):           {correct_cnt}")
    print(f"  No WP Data yet:             {nowp_cnt}")

    if not top5.empty:
        print(f"\n  Top 5 discrepancies (WP vs latest HG):")
        print(f"  {'canonical_key':<35} {'owner':<20} {'delta':>9}")
        print(f"  {'-'*35} {'-'*20} {'-'*9}")
        for _, row in top5.iterrows():
            owner_disp = str(row.get("owner", ""))[:19]
            delta = row["delta_vs_latest"]
            print(f"  {row['canonical_key']:<35} {owner_disp:<20} {delta:>+9.2f}")
    print("=" * 65 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print("Loading files...")
    portfolio, audit = load_data()

    n_direct = int(portfolio.get("is_direct_payer", pd.Series(False)).sum())
    print(f"  Portfolio: {len(portfolio)} managed units ({n_direct} direct payers)")
    print(f"  Audit:     {len(audit)} WP extraction results")

    joined  = build_joined(portfolio, audit)
    joined  = compute_deltas(joined)
    joined  = categorise(joined)

    print_summary(joined, n_direct)
    write_excel(joined, OUTPUT_PATH)

    # Missing WP hint
    needs_wp = int(portfolio.get("needs_wp_update", pd.Series(False)).sum())
    if needs_wp > 0:
        print(
            f"  {needs_wp} unit(s) missing 2026 HG. "
            f"Run 'python3 -m scripts.request_missing_docs --preview' "
            f"to draft request emails."
        )

    # TODO: After audit complete, sync updated HG values to
    # data/portfolio January 2024 NEW.xlsx via scripts/sync_portfolio.py

    return 0


if __name__ == "__main__":
    sys.exit(main())
