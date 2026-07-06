#!/usr/bin/env python
"""Pull pre-fire age-structure exposure data and merge all exposure variables per fire.

For every fire x census-place row in data/fire-fatality-corrected.csv this script
downloads the place's population age distribution from the Census Bureau (ACS 5-year
table B01001, sex by age) for the last ACS vintage that ended BEFORE the fire year,
aggregates it into 10-year bins (0-9 ... 70-79, 80+; ACS tops out at 85+ so the last
bin is open-ended), and writes:

  data/place-age-distribution.csv   one row per fire x place: bin counts + shares,
                                    the ACS vintage used, and a post-fire flag
  data/fire-exposure.csv            fire-fatality-corrected.csv joined with the age
                                    bins and with structures destroyed per fire
                                    (from the hand-curated, source-cited
                                    data/fire-structures-destroyed.csv)

Data source. With CENSUS_API_KEY set, the official API (api.census.gov) is used —
it has required a key since 2025. Without one, the script falls back to the keyless
JSON endpoint behind data.census.gov (CEDSCI, `/api/access/data/table`), which
serves the same published tables.

Vintage selection. The target vintage is fire_year - 1, so the 5-year estimate
window closes before the fire (e.g. CAMP 2018 -> ACS 2013-2017). Several census
places here were first delineated for the 2020 census (Concow, Moskowite Corner,
Silverado Resort, Allendale, Igo, Ono, ...) and simply do not exist in earlier ACS
releases; for those the script walks forward to the first vintage that has the
place and sets pre_fire_geography = False so the caveat is explicit (for CAMP/
Concow that means a post-fire, depopulated base — treat its *shares* as a proxy
for the pre-fire shape, and keep using population_corrected as the level).

Every place is resolved to a FIPS code by exact-name match against the full place
list for that state and vintage, and every B01001 pull is checked (sum of the 18
sex x bin cells == the table's total) so a bad code or variable mapping fails
loudly instead of producing wrong bins.

Run from the repo root:

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

KEY = os.environ.get("CENSUS_API_KEY", "")
EARLIEST_ACS5 = 2009   # first ACS 5-year release
LATEST_ACS5 = 2024     # newest release to consider (2020-2024, released Dec 2025)

# census_place string in fire-fatality-corrected.csv -> (state FIPS, exact place
# name as it appears in the Census NAME field, minus the ", State" suffix).
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
AGE_VARS = ["B01001_001E"] + [f"B01001_{i:03d}E" for ids in BIN_VARS.values() for i in ids]


def get_json(url: str, params: dict, retries: int = 4):
    """GET with retry/backoff; None on 404, raise on other hard failures."""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=120)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError,
                ValueError) as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status is not None and status < 500 and status != 429:
                raise
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


class OfficialApi:
    """api.census.gov -- requires CENSUS_API_KEY (mandatory since 2025)."""

    BASE = "https://api.census.gov/data"

    def __init__(self, key: str) -> None:
        self.key = key
        self._places: dict[tuple[int, str], dict[str, str] | None] = {}

    def place_list(self, vintage: int, state: str) -> dict[str, str] | None:
        k = (vintage, state)
        if k not in self._places:
            data = get_json(f"{self.BASE}/{vintage}/acs/acs5",
                            {"get": "NAME", "for": "place:*", "in": f"state:{state}",
                             "key": self.key})
            self._places[k] = None if data is None else {
                name.rsplit(",", 1)[0].strip().lower(): fips
                for name, _st, fips in data[1:]
            }
        return self._places[k]

    def age_row(self, vintage: int, state: str, place_fips: str) -> dict[str, str] | None:
        data = get_json(f"{self.BASE}/{vintage}/acs/acs5",
                        {"get": ",".join(AGE_VARS), "for": f"place:{place_fips}",
                         "in": f"state:{state}", "key": self.key})
        if not data or len(data) < 2:
            return None
        return dict(zip(data[0], data[1]))


class CedsciApi:
    """Keyless JSON endpoint behind data.census.gov (serves the same ACS tables)."""

    BASE = "https://data.census.gov/api/access/data/table"

    def __init__(self) -> None:
        self._places: dict[tuple[int, str], dict[str, str] | None] = {}

    def _table(self, vintage: int, geo: str, table: str = "B01001") -> list | None:
        try:
            payload = get_json(self.BASE, {"id": f"ACSDT5Y{vintage}.{table}", "g": geo})
        except requests.HTTPError:
            return None  # unpublished vintage surfaces as a 4xx here
        data = (payload or {}).get("response", {}).get("data")
        return data if data and len(data) >= 2 else None

    def place_list(self, vintage: int, state: str) -> dict[str, str] | None:
        k = (vintage, state)
        if k not in self._places:
            # tiny one-variable table just to enumerate NAME + GEO_ID for every place
            data = self._table(vintage, f"040XX00US{state}$1600000", table="B01003")
            if data is None:
                self._places[k] = None
            else:
                hdr = data[0]
                names = {}
                for vals in data[1:]:
                    row = dict(zip(hdr, vals))
                    geoid = row["GEO_ID"]                      # 1600000US0655520
                    fips = geoid.split("US")[1][len(state):]
                    names[row["NAME"].rsplit(",", 1)[0].strip().lower()] = fips
                self._places[k] = names
        return self._places[k]

    def age_row(self, vintage: int, state: str, place_fips: str) -> dict[str, str] | None:
        data = self._table(vintage, f"160XX00US{state}{place_fips}")
        return dict(zip(data[0], data[1])) if data else None


def make_client():
    if KEY:
        print("using api.census.gov (CENSUS_API_KEY set)")
        return OfficialApi(KEY)
    print("no CENSUS_API_KEY -> using keyless data.census.gov endpoint")
    return CedsciApi()


def resolve(client, vintage: int, state: str, canon: str) -> str | None:
    places = client.place_list(vintage, state)
    return None if places is None else places.get(canon.lower())


def pick_vintage(client, fire_year: int, state: str, canon: str) -> tuple[int, str]:
    """Choose the ACS vintage: fire_year-1 if the place exists there, else the
    nearest usable vintage (one step back for unreleased datasets, then forward
    for places that only exist in newer geography)."""
    preferred = min(fire_year - 1, LATEST_ACS5)
    candidates = [preferred, preferred - 1] + list(range(preferred + 1, LATEST_ACS5 + 1))
    for v in candidates:
        if v < EARLIEST_ACS5:
            continue
        fips = resolve(client, v, state, canon)
        if fips is not None:
            return v, fips
    raise RuntimeError(f"could not find place '{canon}' (state {state}) in any ACS "
                       f"vintage {EARLIEST_ACS5}-{LATEST_ACS5}")


def age_bins(client, vintage: int, state: str, place_fips: str) -> dict[str, int]:
    row = client.age_row(vintage, state, place_fips)
    if row is None:
        raise RuntimeError(f"no B01001 data for place {state}{place_fips} in ACS {vintage}")
    total = int(row["B01001_001E"])
    bins = {b: sum(int(row[f"B01001_{i:03d}E"]) for i in ids) for b, ids in BIN_VARS.items()}
    if sum(bins.values()) != total:
        raise RuntimeError(
            f"bin sum {sum(bins.values())} != total {total} for {state}{place_fips} "
            f"ACS {vintage} -- variable mapping is wrong, refusing to write bad data")
    return {"total": total, **bins}


def main() -> None:
    corr = pd.read_csv(CORRECTED)
    sd02 = pd.read_csv(SD02, encoding="latin-1")
    years = sd02.set_index(["Fire", "census place"])["Year"].to_dict()

    missing = [p for p in corr["census_place"].unique() if p not in PLACE_CANON]
    if missing:
        sys.exit(f"no canonical place mapping for: {missing}")

    client = make_client()
    rows = []
    for _, r in corr.iterrows():
        fire, place = r["Fire"], r["census_place"]
        fire_year = int(years[(fire, place)])
        state, canon = PLACE_CANON[place]
        vintage, fips = pick_vintage(client, fire_year, state, canon)
        bins = age_bins(client, vintage, state, fips)
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
