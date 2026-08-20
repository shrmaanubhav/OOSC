"""PPAC PDF parsing -- authoritative refinery capacity data (design doc trap
#9: "verify every capacity number against the PPAC Ready Reckoner refinery
table -- do not trust memory or Wikipedia"). One parser for one table,
snapshotted to CSV. Never re-parsed at demo time -- run this once, commit
the snapshot, everything downstream reads the CSV.

Live-verified source (2026-08-20):
  https://ppac.gov.in/download.php?file=rep_studies/1784899305_The_PPAC_Ready_Reckoner_FY_2025%E2%80%9326_Final.pdf
  Table 4.1 "Refineries: Installed Capacity and Crude Oil Processing", page 65 (1-indexed).

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

_ROW_RE = re.compile(
    r"^(\d+)\s+(.+?)\s+([\d.]+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+$"
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
        rows.append(
            {
                "sr_no": sr_no,
                "name": name,
                "operator": OPERATOR_BY_NAME.get(name, "UNKNOWN"),
                "capacity_mmtpa": capacity_mmtpa,
                "capacity_kbd": round(capacity_mmtpa * 20, 1),  # standard industry approximation
            }
        )

    df = pd.DataFrame(rows)
    assert len(df) == 23, f"expected 23 refineries in Table 4.1, parsed {len(df)}"
    unknown = df[df["operator"] == "UNKNOWN"]
    assert unknown.empty, f"unmapped refinery names, add to OPERATOR_BY_NAME: {list(unknown['name'])}"
    return df


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


def _self_check() -> None:
    """No network, no PDF: regex parsing against a synthetic copy of the
    exact line format PDF extraction produced (verified live 2026-08-20)."""
    synthetic_lines = [
        "PPAC READY RECKONER",
        "Table 4.1 : Refineries: Installed Capacity and Crude Oil Processing",
        "1 Barauni 6.0 5.5 5.6 6.8 6.6 6.5 6.4 6.4",
        "10 Mumbai 9.5 7.4 5.6 9.8 9.6 10.0 10.0 10.0",
        "13 Mumbai 12.0 12.9 14.4 14.5 15.1 15.5 16.0 16.0",
        "21 RIL-Jamnagar (DTA) 33.0 34.1 34.8 34.4 34.4 35.0 33.6 33.6",
        "IOCL total 70.3 62.4 67.7 72.4 73.3 71.6 75.5 75.5",  # must NOT match _ROW_RE
    ]
    text = "\n".join(synthetic_lines)

    class _FakePage:
        def extract_text(self):
            return text

    rows = []
    for line in text.split("\n"):
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        sr_no = int(m.group(1))
        name = _NAME_OVERRIDES.get(sr_no, m.group(2).strip())
        rows.append({"sr_no": sr_no, "name": name, "capacity_mmtpa": float(m.group(3))})

    assert len(rows) == 4, rows  # "IOCL total" line correctly excluded
    assert rows[0] == {"sr_no": 1, "name": "Barauni", "capacity_mmtpa": 6.0}
    assert rows[1]["name"] == "Mumbai (HPCL)"  # disambiguated via _NAME_OVERRIDES
    assert rows[2]["name"] == "Mumbai (BPCL)"
    assert rows[3]["name"] == "RIL-Jamnagar (DTA)"

    print("[ppac] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
