#!/usr/bin/env python
"""Pull pre-fire age-structure exposure data and merge all exposure variables per fire.

For every fire x census-place row in data/fire-fatality-corrected.csv this script
downloads the place's population age distribution from the Census Bureau API
(ACS 5-year table B01001, sex by age) for the last ACS vintage that ended BEFORE
the fire year, aggregates it into 10-year bins (0-9 ... 70-79, 80+; ACS tops out
at 85+ so the last bin is open-ended), and writes:

  data/place-age-distribution.csv   one row per fire x place: bin counts + shares,
                                    the ACS vintage used, and a post-fire flag
  data/fire-exposure.csv            fire-fatality-corrected.csv joined with the age
                                    bins and with structures destroyed per fire
                                    (from the hand-curated, source-cited
                                    data/fire-structures-destroyed.csv)

Vintage selection. The target vintage is fire_year - 1, so the 5-year estimate
window closes before the fire (e.g. CAMP 2018 -> ACS 2013-2017). Several census
places here were first delineated for the 2020 census (Concow, Moskowite Corner,
Silverado Resort, Allendale, Igo, Ono, ...) and simply do not exist in earlier ACS
releases; for those the script walks forward to the first vintage that has the
place and sets pre_fire_geography = False so the caveat is explicit (for CAMP/
Concow that means a post-fire, depopulated base — treat its *shares* as a proxy
for the pre-fire shape, and keep using population_corrected as the level).

Every place is resolved to a FIPS code by exact-name match against the API's own
place list for that state and vintage, and every B01001 pull is checked
(sum of the 18 sex x bin cells == the table's total) so a bad code or variable
mapping fails loudly instead of producing wrong bins.

Requires outbound HTTPS to api.census.gov. No API key needed at this volume;
set CENSUS_API_KEY to use one anyway. Run from the repo root:

  python scripts/fetch_exposure_data.py

Idempotent -- overwrites the two output CSVs in place.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CORRECTED = ROOT / "data" / "fire-fatality-corrected.csv"
SD02 = ROOT / "study" / "data" / "pnas.2535081123.sd02.csv"
STRUCTURES = ROOT / "data" / "fire-structures-destroyed.csv"
OUT_AGES = ROOT / "data" / "place-age-distribution.csv"
OUT_MERGED = ROOT / "data" / "fire-exposure.csv"

API = "https://api.census.gov/data"
KEY = os.environ.get("CENSUS_API_KEY", "")
EARLIEST_ACS5 = 2009   # first ACS 5-year release
LATEST_ACS5 = 2024     # newest release to consider (2020-2024, released Dec 2025)

# census_place string in fire-fatality-corrected.csv -> (state FIPS, exact place
# name as it appears in the Census API NAME field, minus the ", State" suffix).
# Fixes the workbook's spelling quirks (Lahiaina, Silvarado, Weed City, Manitou).
PLACE_CANON: dict[str, tuple[str, str]] = {
    "Lahiaina": ("15", "Lahaina CDP"),
    "Paradise": ("06", "Paradise town"),
    "Altadena": ("06", "Altadena CDP"),
    "Berry Creek": ("06", "Berry Creek CDP"),
    "Gatlinburg": ("47", "Gatlinburg city"),
    "Larkfield-Wikiup CDP": ("06", "Larkfield-Wikiup CDP"),
    "Concow": ("06", "Concow CDP"),
    "Magalia": ("06", "Magalia CDP"),
    "Redwood Valley": ("06", "Redwood Valley CDP"),
    "Malibu": ("06", "Malibu city"),
    "Silvarado Resort": ("06", "Silverado Resort CDP"),
    "Keswick": ("06", "Keswick CDP"),
    "Klamath CDP": ("06", "Klamath CDP"),
    "Hidden Valley Lake CDP, California": ("06", "Hidden Valley Lake CDP"),
    "Igo": ("06", "Igo CDP"),
    "Loma Rica": ("06", "Loma Rica CDP"),
    "Moskowite Corner CDP": ("06", "Moskowite Corner CDP"),
    "Potrero": ("06", "Potrero CDP"),
    "Mountain Ranch": ("06", "Mountain Ranch CDP"),
    "Lake Isabella": ("06", "Lake Isabella CDP"),
    "East Hemet": ("06", "East Hemet CDP"),
    "Allendale CDP": ("06", "Allendale CDP"),
    "Weed City": ("06", "Weed city"),
    "Calimesa": ("06", "Calimesa city"),
    "Happy Camp CDP": ("06", "Happy Camp CDP"),
    "Manitou": ("08", "Manitou Springs city"),
    "Ono": ("06", "Ono CDP"),
    "Grass Valley": ("06", "Grass Valley city"),
    "Davenport": ("06", "Davenport CDP"),
    "Hornbrook": ("06", "Hornbrook CDP"),
    "Walker": ("06", "Walker CDP"),
    "Glen Ellen": ("06", "Glen Ellen CDP"),
    "Topanga": ("06", "Topanga CDP"),
    "Santa Paula": ("06", "Santa Paula city"),
    "Calistoga": ("06", "Calistoga city"),
}

# B01001 sex-by-age cells -> 10-year bins. Male cells 003-025, female 027-049.
BIN_VARS: dict[str, list[int]] = {
    "0_9": [3, 4, 27, 28],                 # <5, 5-9
    "10_19": [5, 6, 7, 29, 30, 31],        # 10-14, 15-17, 18-19
    "20_29": [8, 9, 10, 11, 32, 33, 34, 35],   # 20, 21, 22-24, 25-29
    "30_39": [12, 13, 36, 37],             # 30-34, 35-39
    "40_49": [14, 15, 38, 39],
    "50_59": [16, 17, 40, 41],
    "60_69": [18, 19, 20, 21, 42, 43, 44, 45],  # 60-61, 62-64, 65-66, 67-69
    "70_79": [22, 23, 46, 47],
    "80p": [24, 25, 48, 49],               # 80-84, 85+
}
BIN_LABELS = list(BIN_VARS.keys())
ALL_VARS = ["B01001_001E"] + [f"B01001_{i:03d}E" for ids in BIN_VARS.values() for i in ids]


def get_json(url: str, params: dict, retries: int = 4) -> list | None:
    """GET a Census API endpoint; None on 404 (dataset/geo not published), raise otherwise."""
    if KEY:
        params = {**params, "key": KEY}
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status is not None and status < 500 and status != 429:
                raise
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


class Acs:
    """Thin ACS 5-year client with per-(vintage, state) place-list caching."""

    def __init__(self) -> None:
        self._places: dict[tuple[int, str], dict[str, str] | None] = {}

    def place_list(self, vintage: int, state: str) -> dict[str, str] | None:
        """Map lower-cased place name (no ', State' suffix) -> place FIPS.
        None if this vintage isn't published for ACS 5-year."""
        k = (vintage, state)
        if k not in self._places:
            data = get_json(f"{API}/{vintage}/acs/acs5",
                            {"get": "NAME", "for": "place:*", "in": f"state:{state}"})
            if data is None:
                self._places[k] = None
            else:
                names = {}
                for name, _st, fips in data[1:]:
                    names[name.rsplit(",", 1)[0].strip().lower()] = fips
                self._places[k] = names
        return self._places[k]

    def resolve(self, vintage: int, state: str, canon: str) -> str | None:
        places = self.place_list(vintage, state)
        if places is None:
            return None
        return places.get(canon.lower())

    def age_bins(self, vintage: int, state: str, place_fips: str) -> dict[str, int]:
        data = get_json(f"{API}/{vintage}/acs/acs5",
                        {"get": ",".join(ALL_VARS), "for": f"place:{place_fips}",
                         "in": f"state:{state}"})
        if not data or len(data) < 2:
            raise RuntimeError(f"no B01001 data for place {state}{place_fips} in ACS {vintage}")
        row = dict(zip(data[0], data[1]))
        total = int(row["B01001_001E"])
        bins = {b: sum(int(row[f"B01001_{i:03d}E"]) for i in ids) for b, ids in BIN_VARS.items()}
        if sum(bins.values()) != total:
            raise RuntimeError(
                f"bin sum {sum(bins.values())} != total {total} for {state}{place_fips} "
                f"ACS {vintage} -- variable mapping is wrong, refusing to write bad data")
        return {"total": total, **bins}


def pick_vintage(acs: Acs, fire_year: int, state: str, canon: str) -> tuple[int, str]:
    """Choose the ACS vintage: fire_year-1 if the place exists there, else the
    nearest usable vintage (one step back for unreleased datasets, then forward
    for places that only exist in newer geography)."""
    preferred = min(fire_year - 1, LATEST_ACS5)
    candidates = [preferred, preferred - 1] + list(range(preferred + 1, LATEST_ACS5 + 1))
    for v in candidates:
        if v < EARLIEST_ACS5:
            continue
        fips = acs.resolve(v, state, canon)
        if fips is not None:
            return v, fips
    raise RuntimeError(f"could not find place '{canon}' (state {state}) in any ACS "
                       f"vintage {EARLIEST_ACS5}-{LATEST_ACS5}")


def main() -> None:
    corr = pd.read_csv(CORRECTED)
    sd02 = pd.read_csv(SD02, encoding="latin-1")
    years = sd02.set_index(["Fire", "census place"])["Year"].to_dict()

    missing = [p for p in corr["census_place"].unique() if p not in PLACE_CANON]
    if missing:
        sys.exit(f"no canonical place mapping for: {missing}")

    acs = Acs()
    rows = []
    for _, r in corr.iterrows():
        fire, place = r["Fire"], r["census_place"]
        fire_year = int(years[(fire, place)])
        state, canon = PLACE_CANON[place]
        vintage, fips = pick_vintage(acs, fire_year, state, canon)
        bins = acs.age_bins(vintage, state, fips)
        total = bins.pop("total")
        pre_fire = vintage < fire_year
        rec = {
            "Fire": fire, "census_place": place, "fire_year": fire_year,
            "acs_vintage": vintage, "pre_fire_geography": pre_fire,
            "place_geoid": f"{state}{fips}", "acs_place_name": canon,
            "acs_total_pop": total,
        }
        for b in BIN_LABELS:
            rec[f"pop_{b}"] = bins[b]
        for b in BIN_LABELS:
            rec[f"share_{b}"] = round(bins[b] / total, 4) if total else float("nan")
        rows.append(rec)
        flag = "" if pre_fire else "  [post-fire geography/vintage]"
        print(f"{fire} / {place}: ACS {vintage}, pop {total}{flag}")

    ages = pd.DataFrame(rows)
    ages.to_csv(OUT_AGES, index=False)
    print(f"\nwrote {OUT_AGES.relative_to(ROOT)}  ({len(ages)} rows)")

    structures = pd.read_csv(STRUCTURES)
    unsourced = structures[structures["source_url"].isna()]
    if len(unsourced):
        sys.exit(f"structures rows without a source: {unsourced['Fire'].tolist()}")
    no_struct = set(corr["Fire"]) - set(structures["Fire"])
    if no_struct:
        sys.exit(f"fires missing from {STRUCTURES.name}: {sorted(no_struct)}")

    merged = (
        corr
        .merge(structures[["Fire", "structures_destroyed"]], on="Fire", how="left")
        .merge(ages.drop(columns=["acs_place_name"]), on=["Fire", "census_place"], how="left")
    )
    merged.to_csv(OUT_MERGED, index=False)
    print(f"wrote {OUT_MERGED.relative_to(ROOT)}  ({len(merged)} rows, {merged.shape[1]} cols)")


if __name__ == "__main__":
    main()
