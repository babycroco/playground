"""
audit/unit_matcher.py — Unit ID Normalizer & Matcher

Canonical matching module for reconciling unit identifiers across inconsistent
German property data sources (audit_report.csv, payment files, portfolio sheets,
Dropbox paths).

Usage:
    from audit.unit_matcher import normalize_street, normalize_unit, make_canonical_key, match_unit, build_match_report
"""

import re
import difflib
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Street suffix normalization map
# ---------------------------------------------------------------------------

_SUFFIX_MAP = [
    # Straße variants — order matters (longer patterns first)
    (r"STRA(?:SSE|ẞE|ße|sse)\b\.?", "STR"),
    (r"STR(?:ASZE)?\b\.?", "STR"),
    # Platz variants
    (r"\bPLATZ\b\.?", "PLATZ"),
    (r"\bPL\b\.?", "PLATZ"),
    # Other suffixes — no abbreviation, just uppercase
    (r"\bALLEE\b\.?", "ALLEE"),
    (r"\bALLÉE\b\.?", "ALLEE"),
    (r"\bDAMM\b\.?", "DAMM"),
    (r"\bWEG\b\.?", "WEG"),
    (r"\bRING\b\.?", "RING"),
    (r"\bUFER\b\.?", "UFER"),
]

# Street keyword detection — used to strip owner names
_STREET_KEYWORDS = [
    "STRASSE", "STRASSE", "STRABE", "STR", "PLATZ", "ALLEE", "ALLEE",
    "DAMM", "WEG", "RING", "UFER", "GASSE", "CHAUSSEE",
]


def normalize_street(raw_street: str) -> str:
    """
    Normalize any street format to a canonical uppercase key.

    Steps:
      1. Strip owner names (text before the actual street name)
      2. Normalize suffix variants (Straße → STR, Platz → PLATZ, etc.)
      3. Strip building sub-numbers (80/80a, 80_80a → 80)
      4. Remove dots, special chars; replace spaces with _
      5. Uppercase

    Examples:
      "Alfred Rosenfeld Residenzstr. 129"  → "RESIDENZSTR_129"
      "Residenzstraße 129"                 → "RESIDENZSTR_129"
      "Bornholmer Str. 80/80a"             → "BORNHOLMERSTR_80"
      "Bornholmerstr. 80_80a"              → "BORNHOLMERSTR_80"
    """
    if not raw_street or not isinstance(raw_street, str):
        return ""

    s = raw_street.strip()

    # 1. Strip owner name: detect position of street keyword and take from there.
    #    "Alfred Rosenfeld Residenzstr. 129" → "Residenzstr. 129"
    s = _strip_owner_prefix(s)

    # 2. Uppercase for uniform processing
    s = s.upper()

    # 3. Normalize street suffixes
    for pattern, replacement in _SUFFIX_MAP:
        s = re.sub(pattern, replacement, s, flags=re.IGNORECASE)

    # 4. Strip building sub-numbers: "80/80a" → "80", "80_80a" → "80"
    #    Pattern: a number followed by /NNNx or _NNNx where x is optional letter
    s = re.sub(r"(\d+)[/_]\d+[A-Z]?", r"\1", s)

    # 5. Remove dots and special characters except digits, letters (incl. German),
    #    and underscores (we use _ as separator)
    s = re.sub(r"[.\-,;:'\"()]", "", s)

    # 6. Replace runs of whitespace with single underscore
    s = re.sub(r"\s+", "_", s.strip())

    # 7. Collapse multiple underscores
    s = re.sub(r"_+", "_", s)

    # 8. Merge standalone suffix tokens back into the preceding street name.
    #    "BORNHOLMER_STR_80" → "BORNHOLMERSTR_80"
    #    "KASTANIEN_ALLEE_12" → "KASTANIENALLEE_12"
    _standalone_suffixes = ["STR", "PLATZ", "ALLEE", "DAMM", "WEG", "RING", "UFER"]
    for sfx in _standalone_suffixes:
        s = re.sub(rf"([A-Z0-9])_{sfx}(_|$)", rf"\1{sfx}\2", s)

    return s.strip("_")


def _strip_owner_prefix(street: str) -> str:
    """
    Remove owner name that precedes the actual street in some payment files.

    Strategy:
      - Tokenize by whitespace
      - Find the last token that contains a street keyword
      - If the keyword is a STANDALONE suffix token (e.g. "Str."), the real
        street name begins at the token BEFORE it, so include that token too
      - Only strip the prefix when there are >= 2 tokens before the street group

    "Alfred Rosenfeld Residenzstr. 129" → "Residenzstr. 129"
    "Shavit, Assaf Bornholmerstr. 80"   → "Bornholmerstr. 80"
    "Bornholmer Str. 80/80a"            → "Bornholmer Str. 80/80a"  (unchanged)
    "Residenzstr. 129"                  → "Residenzstr. 129"  (unchanged)
    """
    tokens = street.split()
    if len(tokens) <= 1:
        return street

    upper_tokens = [t.upper().rstrip(".,;") for t in tokens]

    # Find the last token index that contains a street keyword
    street_tok_idx = -1
    keyword_is_standalone = False
    for i, tok_upper in enumerate(upper_tokens):
        for kw in _STREET_KEYWORDS:
            if tok_upper == kw:
                # Exact standalone suffix (e.g. "STR", "PL")
                street_tok_idx = i
                keyword_is_standalone = True
                break
            elif tok_upper.endswith(kw) and len(tok_upper) > len(kw):
                # Embedded suffix (e.g. "RESIDENZSTR")
                street_tok_idx = i
                keyword_is_standalone = False
                break

    if street_tok_idx < 0:
        return street  # No street keyword found

    # The street group starts at street_tok_idx; if it's standalone, include
    # the preceding token (the street name part, e.g. "Bornholmer")
    street_group_start = street_tok_idx
    if keyword_is_standalone and street_tok_idx > 0:
        street_group_start = street_tok_idx - 1

    # Only strip if there are >= 2 tokens before the street group (owner name)
    if street_group_start < 2:
        return street

    return " ".join(tokens[street_group_start:])


def normalize_unit(raw_unit: str) -> str:
    """
    Normalize any unit format to a clean numeric string.

    Strips:
      - Prefixes: WE, WE-, WE , Whg., Whg, Wohnung, Apt.
      - Suffixes: (c), (n), (a), - Furnished, - furnished, trailing letters
      - Owner names that sometimes follow the number
      - All whitespace

    Examples:
      "WE 15 c"         → "15"
      "WE28 (n)"        → "28"
      "WE-06"           → "6"
      "15"              → "15"
      "Whg. 7"          → "7"
      "Wohnung 12"      → "12"
      "WE 15 - Furnished" → "15"
    """
    if not raw_unit or not isinstance(raw_unit, str):
        return ""

    s = raw_unit.strip()

    # 1. Strip known prefixes (case-insensitive)
    s = re.sub(
        r"^(?:Wohnung|Whg\.?|WE[-\s]?|Apt\.?\s*)",
        "",
        s,
        flags=re.IGNORECASE,
    ).strip()

    # 2. Extract just the leading numeric portion, stripping leading zeros
    #    so zero-padded variants ("06") and plain ("6") produce the same key.
    #    "15 c" → "15", "06" → "6", "28 (n)" → "28"
    m = re.match(r"^(\d+)", s)
    if m:
        return str(int(m.group(1)))

    # 3. Fallback: strip all non-digit chars and return
    digits = re.sub(r"\D", "", s)
    return str(int(digits)) if digits else ""


def make_canonical_key(street: str, unit: str) -> str:
    """
    Combine normalized street + unit into a single match key.

    Format: {normalized_street}_WE{normalized_unit}

    Examples:
      ("Residenzstr. 129", "WE 15 c")   → "RESIDENZSTR_129_WE15"
      ("Bornholmerstr. 80_80a", "WE28") → "BORNHOLMERSTR_80_WE28"
    """
    norm_street = normalize_street(street)
    norm_unit = normalize_unit(unit)
    if not norm_street or not norm_unit:
        return ""
    return f"{norm_street}_WE{norm_unit}"


def match_unit(
    query_street: str,
    query_unit: str,
    inventory_df: pd.DataFrame,
    street_col: str = "street",
    unit_col: str = "unit",
    key_col: str = "canonical_key",
) -> dict:
    """
    Find the best match in inventory_df for a given raw street + unit.

    Matching tiers:
      Tier 1 — Exact match on canonical key
      Tier 2 — Exact street match + fuzzy unit (handles sub-unit suffixes)
      Tier 3 — Fuzzy street match (SequenceMatcher > 0.6) + exact unit
      Tier 4 — No match — returns top 3 candidates for manual review

    Returns:
    {
        "matched": bool,
        "confidence": "exact" | "fuzzy" | "none",
        "canonical_key": str,
        "inventory_row": dict | None,
        "candidates": [...]   # populated only on Tier 4
    }
    """
    if inventory_df is None or inventory_df.empty:
        return _no_match(query_street, query_unit, [])

    query_key = make_canonical_key(query_street, query_unit)
    query_norm_street = normalize_street(query_street)
    query_norm_unit = normalize_unit(query_unit)

    # Ensure canonical_key column exists in inventory
    if key_col not in inventory_df.columns:
        inventory_df = _add_canonical_keys(inventory_df, street_col, unit_col, key_col)

    # --- Tier 1: Exact canonical key match ---
    exact_rows = inventory_df[inventory_df[key_col] == query_key]
    if not exact_rows.empty:
        row = exact_rows.iloc[0].to_dict()
        return {
            "matched": True,
            "confidence": "exact",
            "canonical_key": query_key,
            "inventory_row": row,
            "candidates": [],
        }

    # Pre-compute normalized streets for remaining tiers
    if "_norm_street" not in inventory_df.columns:
        inventory_df = inventory_df.copy()
        inventory_df["_norm_street"] = inventory_df[street_col].apply(normalize_street)
        inventory_df["_norm_unit"] = inventory_df[unit_col].apply(normalize_unit)

    # --- Tier 2: Exact street + fuzzy unit ---
    street_matches = inventory_df[inventory_df["_norm_street"] == query_norm_street]
    if not street_matches.empty:
        # Try to find unit where the query unit is a prefix of or matches closely
        for _, row in street_matches.iterrows():
            inv_unit = str(row["_norm_unit"])
            # Fuzzy: query unit starts with inventory unit or vice versa
            if (
                query_norm_unit.lstrip("0") == inv_unit.lstrip("0")
                or inv_unit.startswith(query_norm_unit.lstrip("0"))
                or query_norm_unit.startswith(inv_unit.lstrip("0"))
            ):
                fuzzy_key = f"{query_norm_street}_WE{inv_unit}"
                return {
                    "matched": True,
                    "confidence": "fuzzy",
                    "canonical_key": fuzzy_key,
                    "inventory_row": row.to_dict(),
                    "candidates": [],
                }

    # --- Tier 3: Fuzzy street + exact unit ---
    all_norm_streets = inventory_df["_norm_street"].unique().tolist()
    close_streets = difflib.get_close_matches(
        query_norm_street, all_norm_streets, n=3, cutoff=0.6
    )
    if close_streets:
        best_street = close_streets[0]
        candidates = inventory_df[
            (inventory_df["_norm_street"] == best_street)
            & (inventory_df["_norm_unit"] == query_norm_unit)
        ]
        if not candidates.empty:
            row = candidates.iloc[0].to_dict()
            fuzzy_key = make_canonical_key(row.get(street_col, ""), row.get(unit_col, ""))
            return {
                "matched": True,
                "confidence": "fuzzy",
                "canonical_key": fuzzy_key,
                "inventory_row": row.to_dict(),
                "candidates": [],
            }

    # --- Tier 4: No match ---
    # Build top 3 candidates by street similarity for manual review
    candidates = _get_top_candidates(
        query_norm_street, query_norm_unit, inventory_df, n=3
    )
    return _no_match(query_street, query_unit, candidates)


def _no_match(query_street: str, query_unit: str, candidates: list) -> dict:
    return {
        "matched": False,
        "confidence": "none",
        "canonical_key": make_canonical_key(query_street, query_unit),
        "inventory_row": None,
        "candidates": candidates,
    }


def _get_top_candidates(
    norm_street: str,
    norm_unit: str,
    inventory_df: pd.DataFrame,
    n: int = 3,
) -> list:
    """Return top-N rows from inventory ranked by street similarity."""
    scored = []
    for _, row in inventory_df.iterrows():
        inv_street = str(row.get("_norm_street", ""))
        ratio = difflib.SequenceMatcher(None, norm_street, inv_street).ratio()
        scored.append((ratio, row.to_dict()))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:n]]


def _add_canonical_keys(
    df: pd.DataFrame,
    street_col: str,
    unit_col: str,
    key_col: str,
) -> pd.DataFrame:
    df = df.copy()
    df[key_col] = df.apply(
        lambda row: make_canonical_key(
            str(row.get(street_col, "")),
            str(row.get(unit_col, "")),
        ),
        axis=1,
    )
    return df


def build_match_report(
    source_df: pd.DataFrame,
    inventory_df: pd.DataFrame,
    street_col: str,
    unit_col: str,
) -> pd.DataFrame:
    """
    Batch-match every row in source_df against inventory_df.

    Adds columns to source_df:
      - canonical_key          — normalized key derived from source row
      - match_confidence       — "exact" | "fuzzy" | "none"
      - matched_inventory_unit_id — canonical_key from the matched inventory row

    Prints a summary of match rates.

    Returns the enriched DataFrame.
    """
    if inventory_df is None or inventory_df.empty:
        raise ValueError("inventory_df must be a non-empty DataFrame")

    # Pre-build canonical keys + norm columns on inventory once
    if "canonical_key" not in inventory_df.columns:
        inventory_df = _add_canonical_keys(inventory_df, "street", "unit", "canonical_key")
    if "_norm_street" not in inventory_df.columns:
        inventory_df = inventory_df.copy()
        inventory_df["_norm_street"] = inventory_df["street"].apply(normalize_street)
        inventory_df["_norm_unit"] = inventory_df["unit"].apply(normalize_unit)

    results = []
    for _, row in source_df.iterrows():
        raw_street = str(row.get(street_col, ""))
        raw_unit = str(row.get(unit_col, ""))
        result = match_unit(raw_street, raw_unit, inventory_df)
        results.append({
            "canonical_key": result["canonical_key"],
            "match_confidence": result["confidence"],
            "matched_inventory_unit_id": (
                result["inventory_row"].get("canonical_key", "")
                if result["inventory_row"]
                else ""
            ),
        })

    enriched = source_df.copy()
    results_df = pd.DataFrame(results, index=source_df.index)
    enriched["canonical_key"] = results_df["canonical_key"]
    enriched["match_confidence"] = results_df["match_confidence"]
    enriched["matched_inventory_unit_id"] = results_df["matched_inventory_unit_id"]

    # Summary
    total = len(enriched)
    exact = (enriched["match_confidence"] == "exact").sum()
    fuzzy = (enriched["match_confidence"] == "fuzzy").sum()
    unmatched = (enriched["match_confidence"] == "none").sum()
    match_rate = (exact + fuzzy) / total * 100 if total > 0 else 0

    print(f"\n{'='*50}")
    print(f"  Match Report Summary")
    print(f"{'='*50}")
    print(f"  Total rows:      {total}")
    print(f"  Exact matches:   {exact}  ({exact/total*100:.1f}%)")
    print(f"  Fuzzy matches:   {fuzzy}  ({fuzzy/total*100:.1f}%)")
    print(f"  Unmatched:       {unmatched}  ({unmatched/total*100:.1f}%)")
    print(f"  Overall rate:    {match_rate:.1f}%")
    print(f"{'='*50}\n")

    logger.info(
        "Match report: %d total, %d exact, %d fuzzy, %d unmatched (%.1f%%)",
        total, exact, fuzzy, unmatched, match_rate,
    )

    return enriched
