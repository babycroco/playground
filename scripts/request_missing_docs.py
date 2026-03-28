"""
scripts/request_missing_docs.py — Automated document request emailer

Finds units with missing or stale Wirtschaftspläne, groups them by building,
and drafts (or sends) formal German emails to the responsible Hausverwaltung.

Usage:
    # Preview all drafts (default — does NOT send)
    python3 -m scripts.request_missing_docs --preview

    # Send via Outlook
    python3 -m scripts.request_missing_docs --send

    # Request a specific document type
    python3 -m scripts.request_missing_docs --doc-type jahresabrechnung --year 2024
    python3 -m scripts.request_missing_docs --doc-type betriebskostenabrechnung --year 2024

    # Limit to one building
    python3 -m scripts.request_missing_docs --building "Residenzstr. 129"

Defaults:
    --doc-type  wirtschaftsplan
    --year      current calendar year
    --preview   (safe default)
"""

import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BASE_DIR       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_PATH     = os.path.join(BASE_DIR, "data", "audit_report.csv")
INVENTORY_PATH = os.path.join(BASE_DIR, "data", "master_inventory.csv")
HV_PATH        = os.path.join(BASE_DIR, "data", "Hausverwaltung_Contact_Info.csv")
LOG_PATH       = os.path.join(BASE_DIR, "data", "document_request_log.csv")

sys.path.insert(0, BASE_DIR)
from audit.unit_matcher import normalize_street

# ---------------------------------------------------------------------------
# Document type display strings (German)
# ---------------------------------------------------------------------------

_DOC_LABELS = {
    "wirtschaftsplan":          "Wirtschaftsplan",
    "jahresabrechnung":         "Jahresabrechnung",
    "betriebskostenabrechnung": "Betriebskostenabrechnung",
    "wohngeldabrechnung":       "Wohngeldabrechnung",
    "einzelabrechnung":         "Einzelabrechnung",
}

_DEDUP_DAYS = 14  # skip re-requesting if last request was within this window


# ---------------------------------------------------------------------------
# Email template
# ---------------------------------------------------------------------------

_EMAIL_TEMPLATE = """\
Sehr geehrte Damen und Herren,

im Rahmen unserer Verwaltungstätigkeit für die Eigentümer der folgenden \
Einheit(en) in Ihrem Verwaltungsbestand benötigen wir folgende Unterlagen:

Objekt: {building_address}

{unit_lines}
Wir bitten Sie, uns die genannten Unterlagen zeitnah per E-Mail zukommen \
zu lassen. Sollten die Dokumente bereits versandt worden sein, bitten wir \
um einen kurzen Hinweis.

Für Rückfragen stehen wir Ihnen gerne zur Verfügung.

Mit freundlichen Grüßen,

Rom Chotzen | Property Manager
Sweet Home Immobilien
Hohenzollerndamm 196, 4. OG, 10717 Berlin
Tel: +49 30 65852933\
"""

_SUBJECT_TEMPLATE = (
    "Anforderung {doc_label} {year} – {building_address}"
)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_audit() -> pd.DataFrame:
    df = pd.read_csv(AUDIT_PATH, dtype=str)
    # Normalise column names to lowercase
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df


def _load_inventory() -> pd.DataFrame:
    df = pd.read_csv(INVENTORY_PATH, dtype=str)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df


def _load_hv_contacts() -> dict:
    """
    Load Hausverwaltung_Contact_Info.csv and return a dict keyed by
    normalized street (e.g. 'BORNHOLMERSTR_80') → {'hv_name': ..., 'hv_email': ...}

    HV file often uses informal names without street suffixes (e.g. "Bornholmer 80"
    instead of "Bornholmerstr. 80"). We store both the exact normalized key AND
    a number-stripped base for fuzzy fallback in _resolve_hv().
    """
    hv_map = {}
    if not os.path.exists(HV_PATH):
        return hv_map
    with open(HV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            building  = row.get("building", "").strip()
            norm_key  = normalize_street(building)
            if norm_key:
                hv_map[norm_key] = {
                    "hv_name":    row.get("hv_name",  "").strip(),
                    "hv_email":   row.get("hv_email", "").strip(),
                    "building_raw": building,
                }
    return hv_map


def _resolve_hv(norm_street: str, hv_map: dict) -> dict | None:
    """
    Look up HV contact for a normalized audit street key.

    1. Exact key match.
    2. Fuzzy fallback: strip suffix tokens and compare base name + number.
       e.g. BORNHOLMERSTR_80 vs BORNHOLMER_80 — both share base BORNHOLMER + 80.
    """
    import re as _re, difflib as _dl

    # Tier 1: exact
    if norm_street in hv_map:
        return hv_map[norm_street]

    # Tier 2: fuzzy — compare with SequenceMatcher, threshold 0.75
    best_ratio = 0.0
    best_info  = None
    for hv_key, info in hv_map.items():
        ratio = _dl.SequenceMatcher(None, norm_street, hv_key).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_info  = info

    if best_ratio >= 0.75:
        return best_info

    # Tier 3: compare just the number suffix (last token) + leading word chars
    def _base_and_num(key: str):
        parts = key.split("_")
        num   = parts[-1] if parts[-1].isdigit() else ""
        base  = _re.sub(r"STR|PLATZ|ALLEE|DAMM|WEG|RING|UFER", "", "_".join(parts[:-1]))
        base  = _re.sub(r"_+", "", base)
        return base, num

    audit_base, audit_num = _base_and_num(norm_street)
    for hv_key, info in hv_map.items():
        hv_base, hv_num = _base_and_num(hv_key)
        if audit_num and hv_num == audit_num and audit_base.startswith(hv_base[:4]):
            return info

    return None


def _load_request_log() -> pd.DataFrame:
    if os.path.exists(LOG_PATH):
        return pd.read_csv(LOG_PATH, dtype=str)
    return pd.DataFrame(columns=[
        "date", "building_address", "unit_ids", "document_type",
        "year_requested", "hv_name", "hv_email", "status",
    ])


def _append_request_log(entries: list[dict]) -> None:
    log_df = _load_request_log()
    new_rows = pd.DataFrame(entries)
    log_df = pd.concat([log_df, new_rows], ignore_index=True)
    log_df.to_csv(LOG_PATH, index=False)


# ---------------------------------------------------------------------------
# Missing-unit detection
# ---------------------------------------------------------------------------

def find_missing_units(
    audit_df: pd.DataFrame,
    current_year: int,
    doc_type: str,
) -> pd.DataFrame:
    """
    Return rows from audit_df that need a document request.

    For wirtschaftsplan:
      - status in ("No WP Found", "Download Failed")
      - OR file_year is present but more than 1 year behind current_year

    For other doc types, return all units (the caller controls scope via
    --building or other filters; detection logic is WP-specific).
    """
    if doc_type != "wirtschaftsplan":
        # For non-WP types all units are potentially eligible; return all
        return audit_df.copy()

    missing_status = audit_df["status"].str.strip().isin(
        ["No WP Found", "Download Failed"]
    )

    stale_year = pd.Series(False, index=audit_df.index)
    if "file_year" in audit_df.columns:
        numeric_year = pd.to_numeric(audit_df["file_year"], errors="coerce")
        stale_year = (current_year - numeric_year) > 1

    return audit_df[missing_status | stale_year].copy()


# ---------------------------------------------------------------------------
# Deduplication against existing log
# ---------------------------------------------------------------------------

def _already_requested(
    log_df: pd.DataFrame,
    norm_street: str,
    doc_type: str,
    year: int,
) -> tuple[bool, str, str]:
    """
    Return (True, date_str, status) if the same building + doc_type + year
    was already requested within _DEDUP_DAYS days.
    Otherwise return (False, "", "").
    """
    if log_df.empty:
        return False, "", ""

    cutoff = date.today() - timedelta(days=_DEDUP_DAYS)
    for _, row in log_df.iterrows():
        if (
            normalize_street(str(row.get("building_address", ""))) == norm_street
            and row.get("document_type", "").lower() == doc_type
            and str(row.get("year_requested", "")) == str(year)
        ):
            try:
                req_date = datetime.strptime(
                    str(row["date"]), "%Y-%m-%d"
                ).date()
            except ValueError:
                continue
            if req_date >= cutoff:
                return True, str(row["date"]), str(row.get("status", ""))

    return False, "", ""


# ---------------------------------------------------------------------------
# Email draft assembly
# ---------------------------------------------------------------------------

def _build_unit_lines(
    units: list[dict],
    doc_label: str,
    year: int,
) -> str:
    lines = []
    for u in units:
        unit_num   = u.get("unit_display", u.get("unit", "?"))
        owner      = u.get("owner", "")
        doc_str    = f"{doc_label} {year}"
        if owner:
            lines.append(f"- WE {unit_num} (Eigentümer: {owner}): {doc_str}")
        else:
            lines.append(f"- WE {unit_num}: {doc_str}")
    return "\n".join(lines)


def build_email_draft(
    building_address: str,
    units: list[dict],
    hv_info: dict,
    doc_type: str,
    year: int,
) -> dict:
    """
    Assemble one email draft for a building.

    Returns:
        {
            "to": str,
            "subject": str,
            "body": str,
            "hv_name": str,
            "building_address": str,
            "unit_ids": str,      # comma-joined
        }
    """
    doc_label    = _DOC_LABELS.get(doc_type, doc_type.capitalize())
    unit_lines   = _build_unit_lines(units, doc_label, year)
    hv_name      = hv_info.get("hv_name", "")
    hv_email     = hv_info.get("hv_email", "")

    body = _EMAIL_TEMPLATE.format(
        building_address=building_address,
        unit_lines=unit_lines + "\n",
    )

    subject = _SUBJECT_TEMPLATE.format(
        doc_label=doc_label,
        year=year,
        building_address=building_address,
    )

    unit_ids = ",".join(
        str(u.get("unit_display", u.get("unit", ""))) for u in units
    )

    return {
        "to":               hv_email,
        "subject":          subject,
        "body":             body,
        "hv_name":          hv_name,
        "building_address": building_address,
        "unit_ids":         unit_ids,
    }


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------

def run(
    doc_type: str,
    year: int,
    send_mode: bool,
    building_filter: str | None,
) -> None:
    audit_df   = _load_audit()
    inventory  = _load_inventory()
    hv_map     = _load_hv_contacts()
    log_df     = _load_request_log()

    # Owner lookup: canonical_key → owner name
    owner_map: dict[str, str] = {}
    if "canonical_key" in inventory.columns and "owner" in inventory.columns:
        for _, row in inventory.iterrows():
            owner_map[str(row["canonical_key"])] = str(row.get("owner", ""))

    missing_df = find_missing_units(audit_df, year, doc_type)

    if missing_df.empty:
        print(f"No units require a {_DOC_LABELS.get(doc_type, doc_type)} request for {year}.")
        return

    # Group by normalized street
    missing_df = missing_df.copy()
    missing_df["_norm_street"] = missing_df["street"].apply(normalize_street)

    if building_filter:
        filter_norm = normalize_street(building_filter)
        missing_df = missing_df[missing_df["_norm_street"] == filter_norm]
        if missing_df.empty:
            print(f"No missing units found for building: {building_filter!r}")
            return

    drafts      = []
    log_entries = []
    skipped     = 0

    for norm_street, group in missing_df.groupby("_norm_street"):
        # Dedup check
        already, req_date, req_status = _already_requested(
            log_df, norm_street, doc_type, year
        )
        if already:
            building_disp = group["street"].iloc[0]
            print(
                f"Skipping {building_disp!r} — request already sent on "
                f"{req_date}, status: {req_status}"
            )
            skipped += 1
            continue

        hv_info = _resolve_hv(norm_street, hv_map)
        if not hv_info:
            building_disp = group["street"].iloc[0]
            print(f"NO HV CONTACT FOUND for {building_disp!r} ({norm_street})")
            continue

        # Representative address (first row's street)
        building_address = group["street"].iloc[0]

        # Build unit list with owner names
        units = []
        for _, row in group.iterrows():
            raw_unit   = str(row.get("unit", "")).strip().lstrip("WEwe").strip()
            unit_disp  = raw_unit or str(row.get("unit", ""))
            from audit.unit_matcher import make_canonical_key
            ckey       = make_canonical_key(str(row.get("street", "")),
                                            str(row.get("unit", "")))
            owner      = owner_map.get(ckey, "")
            units.append({"unit_display": unit_disp, "unit": str(row.get("unit", "")),
                          "owner": owner})

        draft = build_email_draft(building_address, units, hv_info, doc_type, year)
        drafts.append(draft)

        log_entries.append({
            "date":             date.today().isoformat(),
            "building_address": building_address,
            "unit_ids":         draft["unit_ids"],
            "document_type":    _DOC_LABELS.get(doc_type, doc_type),
            "year_requested":   str(year),
            "hv_name":          hv_info.get("hv_name", ""),
            "hv_email":         hv_info.get("hv_email", ""),
            "status":           "drafted",
        })

    # Preview all drafts
    print(f"\n{'='*70}")
    print(f"  EMAIL DRAFTS — {len(drafts)} email(s)  |  {skipped} skipped")
    print(f"{'='*70}\n")

    for i, draft in enumerate(drafts, 1):
        print(f"─── Draft {i}/{len(drafts)} ──────────────────────────────────────────")
        print(f"  To:      {draft['to']}")
        print(f"  Subject: {draft['subject']}")
        print(f"  Units:   {draft['unit_ids']}")
        print()
        print(draft["body"])
        print()

    if not drafts:
        return

    # Send mode
    if send_mode:
        from scripts.email_sender import send_email

        sent  = 0
        failed = 0
        for draft, log_entry in zip(drafts, log_entries):
            success = send_email(
                to=draft["to"],
                subject=draft["subject"],
                body=draft["body"],
            )
            log_entry["status"] = "sent" if success else "drafted"
            if success:
                sent += 1
                print(f"  ✓ Sent to {draft['to']}")
            else:
                failed += 1
                print(f"  ✗ Failed: {draft['to']}")

        print(f"\n  Sent: {sent}  Failed: {failed}")
    else:
        print("  [PREVIEW MODE — use --send to actually send]\n")

    # Always append to log (sent or drafted)
    if log_entries:
        _append_request_log(log_entries)
        print(f"  Log updated: {LOG_PATH}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Draft or send document request emails to Hausverwaltungen."
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--preview", action="store_true", default=True,
        help="Preview drafts only (default, does not send)",
    )
    mode_group.add_argument(
        "--send", action="store_true", default=False,
        help="Actually send emails via Microsoft Graph",
    )
    parser.add_argument(
        "--doc-type",
        default="wirtschaftsplan",
        choices=list(_DOC_LABELS.keys()),
        help="Document type to request (default: wirtschaftsplan)",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=date.today().year,
        help="Year to request (default: current year)",
    )
    parser.add_argument(
        "--building",
        default=None,
        help="Limit requests to one building (partial street name OK)",
    )

    args = parser.parse_args()
    send_mode = args.send

    run(
        doc_type=args.doc_type,
        year=args.year,
        send_mode=send_mode,
        building_filter=args.building,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
