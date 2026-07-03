#!/usr/bin/env python
"""Write data/fire-structure-loss.csv: structures destroyed per fire, with sources.

CAL FIRE publishes structure losses in redbooks and incident pages (PDF/HTML — no
stable machine-readable API), so this is a curated table-as-code: every count was
checked against the CAL FIRE incident page / Top 20 Most Destructive list or, for
out-of-state fires, the equivalent official source, in July 2026. Counts are
"structures destroyed" (all structure types, not homes-only) unless the scope
column says otherwise. Fire names match the `Fire` column of
data/fire-fatality-corrected.csv so the table joins one-to-many onto it
(scripts/merge_fire_data.py does this).

Idempotent — overwrites the CSV in place, no network needed.

Run from the repo root:  python scripts/build_structure_loss.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "fire-structure-loss.csv"

# (fire key in fire-fatality-corrected.csv, year, structures destroyed, scope, source)
STRUCTURE_LOSS: list[tuple[str, int, int, str, str]] = [
    ("CAMP", 2018, 18804, "all structures destroyed",
     "https://www.fire.ca.gov/incidents/2018/11/8/camp-fire/"),
    ("TUBBS", 2017, 5636, "all structures destroyed (+317 damaged)",
     "https://www.fire.ca.gov/incidents/2017/10/8/tubbs-fire-central-lnu-complex/"),
    ("Eaton", 2025, 9419, "all structures destroyed (+1,076 damaged); Top 20 list says 9,418",
     "https://www.fire.ca.gov/incidents/2025/1/7/eaton-fire"),
    ("Palisades", 2025, 6845, "all structures destroyed (+975 damaged); Top 20 list says 6,837",
     "https://www.fire.ca.gov/incidents/2025/1/7/palisades-fire"),
    ("NORTH COMPLEX", 2020, 2352, "all structures destroyed",
     "https://www.fire.ca.gov/our-impact/statistics (Top 20 Most Destructive)"),
    ("LNU LIGHTENING COMPLEX", 2020, 1491, "all structures destroyed",
     "https://www.fire.ca.gov/incidents/2020/8/17/lnu-lightning-complex"),
    ("CZU AUGUST LIGHTENING COMPLEX", 2020, 1490, "all structures destroyed (+140 damaged)",
     "https://www.fire.ca.gov/incidents/2020/8/16/czu-lightning-complex-including-warnella-fire"),
    ("CARR", 2018, 1614, "all structures destroyed (+279 damaged)",
     "https://www.fire.ca.gov/incidents/2018/7/23/carr-fire/"),
    ("WOOLSEY", 2018, 1643, "all structures destroyed (~364 damaged), LA + Ventura",
     "https://www.fire.ca.gov/our-impact/statistics (Top 20 Most Destructive)"),
    ("VALLEY", 2015, 1955, "all structures destroyed",
     "https://www.fire.ca.gov/our-impact/statistics (Top 20 Most Destructive)"),
    ("NUNS", 2017, 1355, "all structures destroyed (merged Nuns complex)",
     "https://www.fire.ca.gov/our-impact/statistics (Top 20 Most Destructive)"),
    ("ATLAS", 2017, 781, "all structures destroyed (~120 damaged)",
     "https://www.fire.ca.gov/our-impact/statistics (Top 20 Most Destructive)"),
    ("THOMAS", 2017, 1063, "all structures destroyed (~280 damaged)",
     "https://www.fire.ca.gov/our-impact/statistics (Top 20 Most Destructive)"),
    ("REDWOOD VALLEY", 2017, 546, "all structures destroyed; CAL FIRE incident page "
     "now shows 543 (+41 damaged)",
     "https://www.fire.ca.gov/incidents/2017/10/8/redwood-valley-fire-mendocino-lake-complex"),
    ("BUTTE", 2015, 965, "all structures destroyed (residential+commercial+other); "
     "921 is the older homes/outbuildings tally",
     "https://www.fire.ca.gov/incidents/2015/9/9/butte-fire/"),
    ("ERSKINE", 2016, 309, "all structures destroyed (~257 homes)",
     "https://en.wikipedia.org/wiki/Erskine_Fire (InciWeb; matched pre-2018 CAL FIRE Top 20)"),
    ("CASCADE", 2017, 264, "all structures destroyed",
     "https://krcrtv.com/news/local/cal-fire-report-sagging-pge-power-lines-caused-cascade-fire"),
]


def main() -> None:
    df = pd.DataFrame(
        STRUCTURE_LOSS,
        columns=["Fire", "fire_year", "structures_destroyed",
                 "structures_scope", "structures_source"],
    ).sort_values("structures_destroyed", ascending=False).reset_index(drop=True)
    assert df["Fire"].is_unique, "duplicate fire keys in STRUCTURE_LOSS"
    df.to_csv(OUT, index=False)
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(df)} fires, "
          f"{df['structures_destroyed'].sum():,} structures destroyed)")


if __name__ == "__main__":
    main()
