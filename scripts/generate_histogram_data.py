#!/usr/bin/env python
"""Generate the tidy data behind the demographic histograms in egress-nb-reanalysis.ipynb.

Reads the authors' fatality workbook (SI dataset sd01) and extracts every victim age,
then writes two CSVs the notebook consumes:

  data/fatality-ages.csv        one row per victim with a known age (age, decade_band, source)
  data/age-exposure-baseline.csv national age structure used to exposure-adjust the histogram

Ages live in the `notes` column in three free-text formats — parenthetical "Name (74)",
comma "Name, 74", and phrase "74-year-old Name" / "Name, age 74" — plus a dedicated `Age`
column on the second sheet (Tubbs fire). The same note is occasionally attached to two
census-place rows of one fire (e.g. Cascade fire victims split across Loma Rica and Grass
Valley); those identical notes are de-duplicated so each person is counted once.

Run from the repo root:  python scripts/generate_histogram_data.py
Idempotent — overwrites the CSVs in place.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "study" / "data" / "pnas.2535081123.sd01.xlsx"

# National age structure, % of population by decade (U.S. Census Bureau 2022 vintage
# estimates, rounded). Sums to ~100; 60+ = 23.7%, broadly consistent with the published
# 65+ share of ~17.3%. Used only as an exposure baseline, not as a precise denominator —
# see the caveat in the notebook (the at-risk WUI population skews older than the nation).
US_POP_SHARE = {
    "0–9": 11.7, "10–19": 12.6, "20–29": 13.4, "30–39": 13.5, "40–49": 12.2,
    "50–59": 12.9, "60–69": 11.6, "70–79": 7.6, "80–89": 3.6, "90–99": 0.85, "100+": 0.03,
}
BAND_EDGES = list(range(0, 110, 10))  # 0,10,...,100
BAND_LABELS = list(US_POP_SHARE.keys())


def extract_ages(text: str) -> list[int]:
    """Pull plausible human ages (1–110) from a free-text fatality note."""
    a: list[int] = []
    a += re.findall(r"\((\d{1,3})\)", text)                                  # Name (74)
    a += re.findall(r"(\d{1,3})\s*-?\s*year-old", text)                      # 74-year-old Name
    a += re.findall(r"\bage\s+(\d{1,3})", text)                              # Name, age 74
    a += re.findall(r"[A-Za-z\.\']\s*,\s*(\d{1,3})(?=\s*[,·\.\n]|\s*$|\s+[A-Z])", text)  # Name, 74
    return [int(x) for x in a if 0 < int(x) <= 110]


def band_of(age: int) -> str:
    idx = min(age // 10, 10)  # 100+ collapses into the final band
    return BAND_LABELS[idx]


def collect_ages() -> pd.DataFrame:
    xl = pd.ExcelFile(XLSX)
    rows: list[dict] = []

    # Sheet 1: ages embedded in the free-text notes column.
    main = xl.parse("redbooks + top 20 fires")
    seen_notes: set[str] = set()
    for note in main["notes"].dropna():
        key = str(note).strip()
        if key in seen_notes:
            continue  # identical note re-attached to a second census place -> same people
        seen_notes.add(key)
        for age in extract_ages(key):
            rows.append({"age": age, "decade_band": band_of(age), "source": "notes"})

    # Sheet 2: Tubbs fire has a structured Age column (rows 5 & 38 of sheet 1 point here).
    tub = xl.parse("Tubbs")
    for age in pd.to_numeric(tub["Age"], errors="coerce").dropna():
        age = int(age)
        if 0 < age <= 110:
            rows.append({"age": age, "decade_band": band_of(age), "source": "tubbs"})

    return pd.DataFrame(rows)


def main() -> None:
    ages = collect_ages()
    ages["decade_band"] = pd.Categorical(ages["decade_band"], categories=BAND_LABELS, ordered=True)
    ages = ages.sort_values("age").reset_index(drop=True)

    ages_path = ROOT / "data" / "fatality-ages.csv"
    ages.to_csv(ages_path, index=False)

    baseline = pd.DataFrame(
        {"decade_band": BAND_LABELS, "us_pop_share_pct": [US_POP_SHARE[b] for b in BAND_LABELS]}
    )
    baseline_path = ROOT / "data" / "age-exposure-baseline.csv"
    baseline.to_csv(baseline_path, index=False)

    n = len(ages)
    a = ages["age"].to_numpy()
    print(f"wrote {ages_path.relative_to(ROOT)}  ({n} victim ages)")
    print(f"wrote {baseline_path.relative_to(ROOT)}  ({len(baseline)} bands)")
    print(f"  median {np.median(a):.0f}, mean {a.mean():.1f}, "
          f"65+ {(a >= 65).mean() * 100:.0f}%, <18 {(a < 18).sum()}")


if __name__ == "__main__":
    main()
