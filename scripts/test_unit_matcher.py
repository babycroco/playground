"""
scripts/test_unit_matcher.py — Validation script for audit/unit_matcher.py

Tests the normalizer and verifies canonical keys round-trip correctly
against managed_portfolio.csv (the current source of truth).

Run with:
    python3 -m scripts.test_unit_matcher
"""

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from audit.unit_matcher import (
    normalize_street,
    normalize_unit,
    make_canonical_key,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def test_normalization():
    """Unit tests for normalize_street and normalize_unit."""
    print("\n" + "=" * 60)
    print("  NORMALIZATION TESTS")
    print("=" * 60)

    street_cases = [
        ("Residenzstr. 129",                  "RESIDENZSTR_129"),
        ("Residenzstraße 129",                "RESIDENZSTR_129"),
        ("Bornholmer Str. 80/80a",            "BORNHOLMERSTR_80"),
        ("Bornholmerstr. 80_80a",             "BORNHOLMERSTR_80"),
        ("Alfred Rosenfeld Residenzstr. 129", "RESIDENZSTR_129"),
        ("Shavit, Assaf Bornholmerstr. 80",   "BORNHOLMERSTR_80"),
        ("Hans Müller Residenzstr. 129",      "RESIDENZSTR_129"),
        ("Bornholmer Str. 80",                "BORNHOLMERSTR_80"),
        ("Kastanienallee 12",                 "KASTANIENALLEE_12"),
        ("Karl-Marx-Platz 5",                 "KARLMARXPLATZ_5"),
        # Real-world messy inputs from Rental_Payments-NEW.xlsx
        ("Wuerzburgerstr.8",                  "WUERZBURGERSTR8"),
        ("Residenz str. 128",                 "RESIDENZSTR_128"),
        ("SONNENALLE 147",                    "SONNENALLE_147"),
        ("wundstrs.16",                       "WUNDSTRS16"),
    ]

    unit_cases = [
        ("WE 15 c",          "15"),
        ("WE28 (n)",          "28"),
        ("WE-06",             "6"),
        ("15",                "15"),
        ("Whg. 7",            "7"),
        ("Wohnung 12",        "12"),
        ("WE 15 - Furnished", "15"),
        ("WE09 - Furnished",  "9"),
        ("WE 03 (a)",         "3"),
        ("WE22",              "22"),
    ]

    street_pass = 0
    for raw, expected in street_cases:
        result = normalize_street(raw)
        ok = result == expected
        if ok:
            street_pass += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] normalize_street({raw!r})")
        if not ok:
            print(f"         Expected: {expected!r}")
            print(f"         Got:      {result!r}")

    unit_pass = 0
    print()
    for raw, expected in unit_cases:
        result = normalize_unit(raw)
        ok = result == expected
        if ok:
            unit_pass += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] normalize_unit({raw!r})")
        if not ok:
            print(f"         Expected: {expected!r}")
            print(f"         Got:      {result!r}")

    print(f"\n  Street tests: {street_pass}/{len(street_cases)} passed")
    print(f"  Unit tests:   {unit_pass}/{len(unit_cases)} passed")

    key_tests = [
        (("Residenzstr. 129",                  "WE 15 c"), "RESIDENZSTR_129_WE15"),
        (("Bornholmerstr. 80_80a",             "WE28"),    "BORNHOLMERSTR_80_WE28"),
        (("Alfred Rosenfeld Residenzstr. 129", "WE 15 c"), "RESIDENZSTR_129_WE15"),
        (("Wuerzburgerstr.8",                  "WE29"),    "WUERZBURGERSTR8_WE29"),
    ]
    print()
    key_pass = 0
    for (s, u), expected in key_tests:
        result = make_canonical_key(s, u)
        ok = result == expected
        if ok:
            key_pass += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] make_canonical_key({s!r}, {u!r})")
        if not ok:
            print(f"         Expected: {expected!r}")
            print(f"         Got:      {result!r}")
    print(f"\n  Key tests:    {key_pass}/{len(key_tests)} passed")

    return street_pass + unit_pass + key_pass, len(street_cases) + len(unit_cases) + len(key_tests)


def test_portfolio_canonical_keys():
    """
    Verify every row in managed_portfolio.csv has a non-empty canonical_key
    and that re-deriving it from street + unit_number produces the same value.
    """
    print("\n" + "=" * 60)
    print("  PORTFOLIO CANONICAL KEY INTEGRITY")
    print("=" * 60)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    portfolio_path = os.path.join(base_dir, "data", "managed_portfolio.csv")

    if not os.path.exists(portfolio_path):
        print("  managed_portfolio.csv not found — run build_managed_portfolio first.")
        return

    df = pd.read_csv(portfolio_path, dtype=str)
    total = len(df)
    empty_keys = df["canonical_key"].isna() | (df["canonical_key"].str.strip() == "")
    print(f"\n  Rows: {total}  |  Empty canonical_key: {empty_keys.sum()}")

    mismatches = 0
    for _, row in df.iterrows():
        derived = make_canonical_key(
            str(row.get("street", "")),
            str(row.get("unit_number", "")),
        )
        stored = str(row.get("canonical_key", "")).strip()
        if derived != stored:
            mismatches += 1
            print(f"  MISMATCH  stored={stored!r}  derived={derived!r}")

    if mismatches == 0:
        print(f"  All {total} canonical keys are consistent ✓")
    else:
        print(f"  {mismatches} mismatches found")


def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    passed, total = test_normalization()
    test_portfolio_canonical_keys()

    print("\n" + "=" * 60)
    print(f"  DONE — {passed}/{total} normalization tests passed")
    print("=" * 60)


if __name__ == "__main__":
    main()
