"""PPAC PDF parsing -- authoritative refinery capacity data (design doc trap
#9: "verify every capacity number against the PPAC Ready Reckoner refinery
table -- do not trust memory or Wikipedia"). Two tables, both snapshotted
to CSV. Never re-parsed at demo time -- run this once, commit the
snapshot, everything downstream reads the CSV.

Live-verified source (2026-08-20):
  https://ppac.gov.in/download.php?file=rep_studies/1784899305_The_PPAC_Ready_Reckoner_FY_2025%E2%80%9326_Final.pdf
  Table 4.1 "Refineries: Installed Capacity and Crude Oil Processing", page 65 (1-indexed).
  Table 8.1 "Indian Basket Crude Oil Price", page 124 (1-indexed).

This PDF is ~32MB and the URL embeds a timestamp/filename that changes
each edition -- it is NOT re-fetched automatically. Update PPAC_URL by
hand when a new Ready Reckoner edition is needed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx
import pandas as pd

PPAC_URL = "https://ppac.gov.in/download.php?file=rep_studies/1784899305_The_PPAC_Ready_Reckoner_FY_2025%E2%80%9326_Final.pdf"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_PDF = DATA_DIR / "raw" / "ppac_ready_reckoner.pdf"
SNAPSHOT_DIR = DATA_DIR / "snapshots" / "ppac"

# Sr.No -> operator, from the section groupings in Table 4.1 (the PDF's
# "IOCL total" / "HPCL total" / etc. subtotal rows, not a separate column)
OPERATOR_BY_NAME = {
    "Barauni": "IOCL", "Koyali": "IOCL", "Haldia": "IOCL", "Mathura": "IOCL",
    "Panipat": "IOCL", "Guwahati": "IOCL", "Digboi": "IOCL", "Bongaigaon": "IOCL",
    "Paradip": "HPCL", "Mumbai (HPCL)": "HPCL", "Visakh": "HPCL",
    "HMEL-Bathinda": "HMEL (HPCL-Mittal JV)",
    "Mumbai (BPCL)": "BPCL", "Kochi": "BPCL",
    "BORL-Bina": "BORL (BPCL-Oman JV)",
    "Manali": "CPCL",
    "CBR": "ONGC-CPCL JV (Cauvery Basin Refinery)",
    "Numaligarh": "NRL (ONGC group)",
    "Tatipaka": "ONGC",
    "MRPL-Mangalore": "MRPL (ONGC subsidiary)",
    "RIL-Jamnagar (DTA)": "Reliance", "RIL-Jamnagar (SEZ)": "Reliance",
    "NEL-Vadinar": "Nayara Energy",
}

# The PDF's "Mumbai" appears twice (row 10 under HPCL, row 13 under BPCL) --
# disambiguated here since OPERATOR_BY_NAME needs unique keys
_NAME_OVERRIDES = {10: "Mumbai (HPCL)", 13: "Mumbai (BPCL)"}

# Row shape: Sr.No, name, Installed Capacity (1 number), then 7 yearly Crude
# Oil Processing figures (2020-21 .. 2025-26, plus a second "2025-26" column
# -- the PDF's own header repeats "2025-26" twice with no further label in
# the extracted text; for most refineries the two are identical, but at
# least one (NEL-Vadinar: 18.9 vs 19.0) genuinely differs, so this is a real
# second column, not a rendering duplicate. Which sub-period each measures
# isn't recoverable from the extracted text -- taking the rightmost
# (final) column as "most recent reported processing" rather than guessing
# which one is more authoritative.
_ROW_RE = re.compile(
    r"^(\d+)\s+(.+?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)$"
)


def parse_refinery_capacity_table(pdf_path: Path) -> pd.DataFrame:
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        table_page = next(
            p for p in pdf.pages if "Table 4.1" in (p.extract_text() or "")
        )
        lines = table_page.extract_text().split("\n")

    rows = []
    for line in lines:
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        sr_no = int(m.group(1))
        name = _NAME_OVERRIDES.get(sr_no, m.group(2).strip())
        capacity_mmtpa = float(m.group(3))
        processing_mmtpa_2025_26 = float(m.group(10))  # rightmost "2025-26" column, see note above
        rows.append(
            {
                "sr_no": sr_no,
                "name": name,
                "operator": OPERATOR_BY_NAME.get(name, "UNKNOWN"),
                "capacity_mmtpa": capacity_mmtpa,
                "capacity_kbd": round(capacity_mmtpa * 20, 1),  # standard industry approximation
                "processing_mmtpa_2025_26": processing_mmtpa_2025_26,
                "processing_kbd_2025_26": round(processing_mmtpa_2025_26 * 20, 1),
            }
        )

    df = pd.DataFrame(rows)
    assert len(df) == 23, f"expected 23 refineries in Table 4.1, parsed {len(df)}"
    unknown = df[df["operator"] == "UNKNOWN"]
    assert unknown.empty, f"unmapped refinery names, add to OPERATOR_BY_NAME: {list(unknown['name'])}"
    return df


_YEAR_RE = re.compile(r"^(\d{4}-\d{2})\s+([\d.]+)$")
_MONTH_RE = re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+([\d.]+)$")
_JUNE_HIGHLIGHT_RE = re.compile(r"June 2026, with the Indian Basket averaging US\$\s*([\d.]+)/bbl")


def parse_india_basket_price(pdf_path: Path) -> dict:
    """Table 8.1 'Indian Basket Crude Oil Price': full-year averages FY2002-03
    through FY2024-25, plus FY2025-26 monthly averages. Table 8.1 itself only
    tabulates monthly figures through May in this edition; June comes from
    the Ready Reckoner's own Chapter Highlights narrative text on the
    preceding page (same document, page 113), quoted verbatim there as
    "...the Indian Basket averaging US$ 83.22/bbl [in June 2026]...".

    Deliberately NOT parsed: a merged line reading "2025-26 2026 : Month
    wise 70.99" -- a pdfplumber column-layout artifact merging the FY
    partial-year average with the "Month wise" sub-header. Which months
    70.99 actually averages isn't recoverable from the extracted text, and
    guessing would violate CLAUDE.md rule 5 (verify every reference number,
    never assume)."""
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        idx = next(i for i, p in enumerate(pdf.pages) if "Table 8.1" in (p.extract_text() or ""))
        table_text = pdf.pages[idx].extract_text()
        highlights_text = pdf.pages[idx - 1].extract_text() or ""

    annual: dict[str, float] = {}
    monthly: dict[str, float] = {}
    for line in table_text.split("\n"):
        s = line.strip()
        y = _YEAR_RE.match(s)
        if y:
            annual[y.group(1)] = float(y.group(2))
        mo = _MONTH_RE.match(s)
        if mo:
            monthly[mo.group(1)] = float(mo.group(2))

    june = _JUNE_HIGHLIGHT_RE.search(re.sub(r"\s+", " ", highlights_text))
    monthly_source = {m: "PPAC Ready Reckoner Table 8.1" for m in monthly}
    if june:
        monthly["June"] = float(june.group(1))
        monthly_source["June"] = "PPAC Ready Reckoner Chapter Highlights narrative (Table 8.1 doesn't tabulate June in this edition)"

    assert len(annual) >= 20, f"expected >=20 full FY rows in Table 8.1, parsed {len(annual)}"
    assert {"March", "April", "May"} <= monthly.keys(), monthly
    return {"annual_usd_bbl": annual, "monthly_2025_26_usd_bbl": monthly, "monthly_source": monthly_source}


def main() -> None:
    RAW_PDF.parent.mkdir(parents=True, exist_ok=True)
    if not RAW_PDF.exists():
        print(f"[ppac] downloading {PPAC_URL}")
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            resp = client.get(PPAC_URL)
            resp.raise_for_status()
            RAW_PDF.write_bytes(resp.content)
        print(f"[ppac]   saved {len(resp.content):,} bytes -> {RAW_PDF}")
    else:
        print(f"[ppac] using cached {RAW_PDF}")

    df = parse_refinery_capacity_table(RAW_PDF)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SNAPSHOT_DIR / "refinery_capacity.csv"
    df.to_csv(out_path, index=False)
    print(f"[ppac] parsed {len(df)} refineries -> {out_path}")
    print(df.to_string(index=False))

    price = parse_india_basket_price(RAW_PDF)
    annual_df = pd.DataFrame(
        [{"fiscal_year": y, "price_usd_bbl": p} for y, p in price["annual_usd_bbl"].items()]
    )
    annual_path = SNAPSHOT_DIR / "india_basket_price_annual.csv"
    annual_df.to_csv(annual_path, index=False)

    monthly_df = pd.DataFrame(
        [
            {"month": m, "price_usd_bbl": p, "source": price["monthly_source"][m]}
            for m, p in price["monthly_2025_26_usd_bbl"].items()
        ]
    )
    monthly_path = SNAPSHOT_DIR / "india_basket_price_monthly_2025_26.csv"
    monthly_df.to_csv(monthly_path, index=False)
    print(f"\n[ppac] parsed {len(annual_df)} annual + {len(monthly_df)} FY2025-26 monthly "
          f"India Basket price points -> {annual_path}, {monthly_path}")
    print(monthly_df.to_string(index=False))


def _self_check() -> None:
    """No network, no PDF: regex parsing against synthetic copies of the
    exact line formats PDF extraction produced (verified live 2026-08-20)."""
    synthetic_lines = [
        "PPAC READY RECKONER",
        "Table 4.1 : Refineries: Installed Capacity and Crude Oil Processing",
        "1 Barauni 6.0 5.5 5.6 6.8 6.6 6.5 6.4 6.4",
        "10 Mumbai 9.5 7.4 5.6 9.8 9.6 10.0 10.0 10.0",
        "13 Mumbai 12.0 12.9 14.4 14.5 15.1 15.5 16.0 16.0",
        "21 RIL-Jamnagar (DTA) 33.0 34.1 34.8 34.4 34.4 35.0 33.6 33.6",
        "23 NEL-Vadinar 20.0 17.1 20.2 18.7 20.3 20.5 18.9 19.0",  # last two columns genuinely differ
        "IOCL total 70.3 62.4 67.7 72.4 73.3 71.6 75.5 75.5",  # must NOT match _ROW_RE
    ]
    text = "\n".join(synthetic_lines)

    rows = []
    for line in text.split("\n"):
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        sr_no = int(m.group(1))
        name = _NAME_OVERRIDES.get(sr_no, m.group(2).strip())
        rows.append({
            "sr_no": sr_no, "name": name,
            "capacity_mmtpa": float(m.group(3)),
            "processing_mmtpa_2025_26": float(m.group(10)),  # rightmost "2025-26" column
        })

    assert len(rows) == 5, rows  # "IOCL total" line correctly excluded
    assert rows[0] == {"sr_no": 1, "name": "Barauni", "capacity_mmtpa": 6.0, "processing_mmtpa_2025_26": 6.4}
    assert rows[1]["name"] == "Mumbai (HPCL)"  # disambiguated via _NAME_OVERRIDES
    assert rows[2]["name"] == "Mumbai (BPCL)"
    assert rows[3]["name"] == "RIL-Jamnagar (DTA)"
    # NEL-Vadinar: rightmost column (19.0) taken, not the identical-looking
    # penultimate one (18.9) -- catches an off-by-one group index regression
    assert rows[4]["processing_mmtpa_2025_26"] == 19.0, rows[4]

    # India Basket price parser: synthetic Table 8.1 + Chapter Highlights
    # text mirroring the real PDF's exact layout, including the merged
    # "2025-26 ... 70.99" line that must NOT be parsed (ambiguous meaning)
    synthetic_table = (
        "PPAC READY RECKONER\nTable 8.1 : Indian Basket Crude Oil Price\n"
        "Indian basket\nYear\n($/bbl)\n2023-24 82.58\n2024-25 78.56\n"
        "2025-26 2026 : Month wise 70.99\nJanuary 63.08\nFebruary 69.01\n"
        "March 113.49\nApril 114.48\nMay 106.23\nNotes:\n"
    )
    synthetic_highlights = (
        "PPAC READY RECKONER\nChapter Highlights\nHowever, international crude oil\n"
        "prices partially softened in June 2026, with the Indian Basket averaging US$ 83.22/bbl,\n"
        "primarily due to the interim ceasefire\n"
    )
    annual, monthly = {}, {}
    for line in synthetic_table.split("\n"):
        s = line.strip()
        y = _YEAR_RE.match(s)
        if y:
            annual[y.group(1)] = float(y.group(2))
        mo = _MONTH_RE.match(s)
        if mo:
            monthly[mo.group(1)] = float(mo.group(2))
    june = _JUNE_HIGHLIGHT_RE.search(re.sub(r"\s+", " ", synthetic_highlights))

    assert annual == {"2023-24": 82.58, "2024-25": 78.56}  # merged "2025-26 ... 70.99" line excluded
    assert monthly == {"January": 63.08, "February": 69.01, "March": 113.49, "April": 114.48, "May": 106.23}
    assert june and float(june.group(1)) == 83.22

    print("[ppac] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
