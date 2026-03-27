"""
scripts/test_unit_matcher.py — Validation script for unit_matcher.py

Tests the normalizer against all data sources and reports match rates.

Run with:
    python3 -m scripts.test_unit_matcher
"""

import sys
import os
import logging

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from audit.unit_matcher import (
    normalize_street,
    normalize_unit,
    make_canonical_key,
    match_unit,
    build_match_report,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def test_normalization():
    """Unit tests for normalize_street and normalize_unit."""
    print("\n" + "=" * 60)
    print("  NORMALIZATION TESTS")
    print("=" * 60)

    street_cases = [
        # (input, expected)
        ("Residenzstr. 129",                "RESIDENZSTR_129"),
        ("Residenzstraße 129",              "RESIDENZSTR_129"),
        ("Bornholmer Str. 80/80a",          "BORNHOLMERSTR_80"),
        ("Bornholmerstr. 80_80a",           "BORNHOLMERSTR_80"),
        ("Alfred Rosenfeld Residenzstr. 129", "RESIDENZSTR_129"),
        ("Shavit, Assaf Bornholmerstr. 80", "BORNHOLMERSTR_80"),
        ("Hans Müller Residenzstr. 129",    "RESIDENZSTR_129"),
        ("Bornholmer Str. 80",              "BORNHOLMERSTR_80"),
        ("Kastanienallee 12",               "KASTANIENALLEE_12"),
        ("Karl-Marx-Platz 5",               "KARLMARXPLATZ_5"),
    ]

    unit_cases = [
        ("WE 15 c",           "15"),
        ("WE28 (n)",           "28"),
        ("WE-06",              "6"),
        ("15",                 "15"),
        ("Whg. 7",             "7"),
        ("Wohnung 12",         "12"),
        ("WE 15 - Furnished",  "15"),
        ("WE09 - Furnished",   "9"),
        ("WE 03 (a)",          "3"),
        ("WE22",               "22"),
    ]

    street_pass = 0
    for raw, expected in street_cases:
        result = normalize_street(raw)
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS":
            street_pass += 1
        print(f"  [{status}] normalize_street({raw!r})")
        if result != expected:
            print(f"         Expected: {expected!r}")
            print(f"         Got:      {result!r}")

    unit_pass = 0
    print()
    for raw, expected in unit_cases:
        result = normalize_unit(raw)
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS":
            unit_pass += 1
        print(f"  [{status}] normalize_unit({raw!r})")
        if result != expected:
            print(f"         Expected: {expected!r}")
            print(f"         Got:      {result!r}")

    print(f"\n  Street tests: {street_pass}/{len(street_cases)} passed")
    print(f"  Unit tests:   {unit_pass}/{len(unit_cases)} passed")

    key_tests = [
        (("Residenzstr. 129", "WE 15 c"),          "RESIDENZSTR_129_WE15"),
        (("Bornholmerstr. 80_80a", "WE28"),         "BORNHOLMERSTR_80_WE28"),
        (("Alfred Rosenfeld Residenzstr. 129", "WE 15 c"), "RESIDENZSTR_129_WE15"),
    ]
    print()
    key_pass = 0
    for (s, u), expected in key_tests:
        result = make_canonical_key(s, u)
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS":
            key_pass += 1
        print(f"  [{status}] make_canonical_key({s!r}, {u!r})")
        if result != expected:
            print(f"         Expected: {expected!r}")
            print(f"         Got:      {result!r}")
    print(f"\n  Key tests:    {key_pass}/{len(key_tests)} passed")


def test_match_against_inventory():
    """Test matching audit_report.csv rows against inventory."""
    print("\n" + "=" * 60)
    print("  MATCHING: audit_report.csv → master_inventory.csv")
    print("=" * 60)

    inventory = pd.read_csv("data/master_inventory.csv")
    audit = pd.read_csv("data/audit_report.csv")

    # Simulate the old match rate (~15%): naive exact string match on raw unit
    old_matches = 0
    for _, row in audit.iterrows():
        raw_unit = str(row["unit"]).strip()
        for _, inv_row in inventory.iterrows():
            if raw_unit == str(inv_row["unit"]).strip():
                old_matches += 1
                break
    old_rate = old_matches / len(audit) * 100
    print(f"\n  Baseline match rate (naive exact): {old_matches}/{len(audit)} = {old_rate:.1f}%")

    # New match rate using unit_matcher
    print("\n  Running build_match_report()...")
    enriched = build_match_report(audit, inventory, street_col="street", unit_col="unit")

    new_matched = (enriched["match_confidence"] != "none").sum()
    new_rate = new_matched / len(enriched) * 100
    print(f"  New match rate:  {new_matched}/{len(enriched)} = {new_rate:.1f}%")
    print(f"  Improvement:     +{new_rate - old_rate:.1f} percentage points")

    if new_rate >= 80:
        print(f"\n  TARGET MET: {new_rate:.1f}% >= 80% ✓")
    else:
        print(f"\n  WARNING: Target not met ({new_rate:.1f}% < 80%)")

    return enriched


def test_match_payment_file():
    """Test matching payment file (Owner_Street + Unit) against inventory."""
    print("\n" + "=" * 60)
    print("  MATCHING: payment_mori_rapoport.csv → master_inventory.csv")
    print("=" * 60)

    payment_path = "data/payment_mori_rapoport.csv"
    if not os.path.exists(payment_path):
        print("  Payment file not found, skipping.")
        return

    inventory = pd.read_csv("data/master_inventory.csv")
    payment = pd.read_csv(payment_path)

    print(f"\n  Payment file has {len(payment)} rows.")
    print("  Running build_match_report()...")
    enriched = build_match_report(
        payment, inventory, street_col="Owner_Street", unit_col="Unit"
    )

    # Show unmatched rows for debugging
    unmatched = enriched[enriched["match_confidence"] == "none"]
    if not unmatched.empty:
        print("\n  Unmatched rows:")
        for _, row in unmatched.iterrows():
            print(f"    Street: {row['Owner_Street']!r}  Unit: {row['Unit']!r}")
            print(f"    Canonical key attempted: {row['canonical_key']!r}")

    return enriched


def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    test_normalization()
    audit_enriched = test_match_against_inventory()
    payment_enriched = test_match_payment_file()

    print("\n" + "=" * 60)
    print("  DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
