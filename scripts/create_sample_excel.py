"""
scripts/create_sample_excel.py — Create sample Rental_Payments-NEW.xlsx

Creates data/Rental_Payments-NEW.xlsx with a Managers sheet containing ~25
representative rows covering all edge cases, plus stub sheets.

Run with:
    python3 -m scripts.create_sample_excel
"""

import os
import openpyxl

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "Rental_Payments-NEW.xlsx")


def create_sample_excel():
    os.makedirs(DATA_DIR, exist_ok=True)

    wb = openpyxl.Workbook()

    # --- Managers sheet ---
    ws_managers = wb.active
    ws_managers.title = "Managers"

    headers = ["Owners", "Property name", "2024", "2025", "2026", "2027"]
    ws_managers.append(headers)

    # Rows covering all edge cases:
    # - Normal numeric values
    # - Formula strings (stored as plain strings, not evaluated)
    # - "They pay on their own" (direct payer)
    # - "LEER" (vacant)
    # - Empty cells (None)
    # - Mixed / multi-address property names
    rows = [
        # (Owner, Property name, 2024, 2025, 2026, 2027)
        ("Alfred Rosenfeld",  "Residenzstr. 129 WE15",                          320.0,  334.50, 334.50,           None),
        ("Hans Müller",       "Residenzstr. 129 WE06",                          260.0,  270.0,  None,             None),
        ("Bauer Maria",       "Residenzstr. 129 WE07",                          295.0,  300.0,  300.0,            None),
        ("Schneider Anna",    "Residenzstr. 129 WE09",                          310.0,  320.0,  320.0,            None),
        ("Richter Sabine",    "Residenzstr. 129 WE11",                          285.0,  293.0,  293.0,            None),
        ("Wolf Ingrid",       "Residenzstr. 129 WE02",                          245.0,  253.0,  253.0,            None),
        ("Becker Helga",      "Residenzstr. 129 WE08",                          300.0,  310.0,  310.0,            None),
        # Formula string — stored as plain string, NOT as Excel formula
        ("Shavit Assaf",      "Bornholmerstr. 80 WE28",                         400.0,  416.0,  "=405.00+11.00",  None),
        # Direct payer
        ("Schmidt Eva",       "Bornholmerstr. 80 WE03",                         355.0,  370.0,  "They pay on their own", None),
        ("Fischer Klaus",     "Bornholmerstr. 80 WE12",                         375.0,  387.0,  None,             None),
        ("Wagner Thomas",     "Bornholmerstr. 80 WE22",                         390.0,  403.0,  403.0,            None),
        ("Hoffmann Petra",    "Bornholmerstr. 80 WE04",                         340.0,  350.0,  None,             None),
        ("Klein Werner",      "Bornholmerstr. 80 WE17",                         380.0,  395.0,  None,             None),
        ("Koch Dieter",       "Bornholmerstr. 80 WE31",                         425.0,  440.0,  440.0,            None),
        ("Schäfer Georg",     "Bornholmerstr. 80 WE19",                         398.0,  413.0,  413.0,            None),
        # Another formula string
        ("Avraham Josef",     "Wuerzburgerstr.8 WE29",                          195.0,  210.0,  "=198.50+12.30",  None),
        ("Levi Sarah",        "Residenz str. 128 WE12",                         280.0,  295.0,  295.0,            None),
        # Missing 2025 and 2026
        ("Ben-David Roni",    "SONNENALLE 147 WE3",                             510.0,  None,   None,             None),
        # Multi-address property name
        ("Montag Tanja",      "Weserstr. 59 WE19/ Wildenbruch 6 / WE 19",      340.0,  355.0,  355.0,            None),
        # Direct payer (lowercase variant)
        ("Goldstein Marc",    "wundstrs.16 WE5",                                220.0,  230.0,  "They pay on their own", None),
        ("Katz Miriam",       "Quitzowstr. 130 WE08",                           185.0,  195.0,  None,             None),
        ("Shapiro Dan",       "Quitzowstr. 130 WE12",                           195.0,  205.0,  205.0,            None),
        # LEER (vacant)
        ("Levy Noa",          "Kastanienallee 25 WE4",                          410.0,  425.0,  "LEER",           None),
        ("Cohen David",       "Kastanienallee 25 WE7",                          385.0,  400.0,  400.0,            None),
        # Completely empty row (only owner name — no property data)
        ("Stern Eli",         "Bornholmerstr. 80 WE28",                         None,   None,   None,             None),
    ]

    for row in rows:
        ws_managers.append(list(row))

    # --- Stub sheets ---
    wb.create_sheet("Paymets")          # intentional typo as in real file
    wb.create_sheet("Grundsteuer")
    wb.create_sheet("גיליון2")          # Hebrew sheet name, empty

    wb.save(OUTPUT_PATH)
    print(f"Created: {OUTPUT_PATH}")
    print(f"  Sheets: {wb.sheetnames}")
    print(f"  Managers rows (excl. header): {ws_managers.max_row - 1}")


if __name__ == "__main__":
    create_sample_excel()
