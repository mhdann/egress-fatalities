#!/usr/bin/env python
"""Assemble the superseding analysis table: data/fire-fatality-enriched.csv.

Left-joins onto data/fire-fatality-corrected.csv (keyed Fire + census_place):

  * fire_year                    from the authors' workbook (sd01)
  * structures_destroyed (+ scope, source)   per FIRE, from data/fire-structure-loss.csv
                                 (regenerate with scripts/build_structure_loss.py)
  * age shares (10-yr bands)     per community, preferred census source only, from
                                 data/community-age-structure.csv
                                 (regenerate with scripts/fetch_community_age_structure.py)

The age-share join is optional: if community-age-structure.csv hasn't been fetched
yet (it needs network access to api.census.gov) the merge still runs and simply
omits those columns. Idempotent — overwrites the output in place.

Run from the repo root:  python scripts/merge_fire_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CORRECTED = ROOT / "data" / "fire-fatality-corrected.csv"
SD01 = ROOT / "study" / "data" / "pnas.2535081123.sd01.xlsx"
STRUCTURES = ROOT / "data" / "fire-structure-loss.csv"
AGES = ROOT / "data" / "community-age-structure.csv"
OUT = ROOT / "data" / "fire-fatality-enriched.csv"

BAND_COL = {  # decade_band -> merged column name
    "0–9": "share_0_9", "10–19": "share_10_19", "20–29": "share_20_29",
    "30–39": "share_30_39", "40–49": "share_40_49", "50–59": "share_50_59",
    "60–69": "share_60_69", "70–79": "share_70_79", "80+": "share_80_plus",
}


def main() -> None:
    df = pd.read_csv(CORRECTED)

    years = (
        pd.ExcelFile(SD01).parse("redbooks + top 20 fires")[["Fire", "Year"]]
        .dropna().drop_duplicates("Fire").set_index("Fire")["Year"].astype(int)
    )
    df.insert(1, "fire_year", df["Fire"].map(years).astype("Int64"))

    if STRUCTURES.exists():
        s = pd.read_csv(STRUCTURES)[
            ["Fire", "structures_destroyed", "structures_scope", "structures_source"]
        ]
        df = df.merge(s, on="Fire", how="left", validate="many_to_one")
        lost = df[df["structures_destroyed"].isna()]["Fire"].unique().tolist()
        if lost:
            print(f"note: no structure-loss row for fires: {lost}", file=sys.stderr)
    else:
        print(f"note: {STRUCTURES.name} missing — run scripts/build_structure_loss.py",
              file=sys.stderr)

    if AGES.exists():
        a = pd.read_csv(AGES)
        a = a[a["preferred"]]
        wide = (
            a.pivot_table(index=["Fire", "census_place"], columns="decade_band",
                          values="share_pct", aggfunc="first")
            .rename(columns=BAND_COL)
            .reindex(columns=list(BAND_COL.values()))
            .reset_index()
        )
        meta = (
            a.groupby(["Fire", "census_place"])
            .agg(age_source=("dataset", "first"),
                 age_total_pop=("total_pop", "first"),
                 age_match_note=("match_note", "first"))
            .reset_index()
        )
        df = df.merge(wide, on=["Fire", "census_place"], how="left") \
               .merge(meta, on=["Fire", "census_place"], how="left")
        df["age_total_pop"] = df["age_total_pop"].astype("Int64")
    else:
        print(f"note: {AGES.name} missing — run scripts/fetch_community_age_structure.py "
              "(needs api.census.gov access); age-share columns omitted", file=sys.stderr)

    df.to_csv(OUT, index=False)
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(df)} rows, {len(df.columns)} cols)")


if __name__ == "__main__":
    main()
