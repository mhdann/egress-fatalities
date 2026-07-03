#!/usr/bin/env python
"""Fetch the pre-fire age structure (10-year bins) of every fire community in
data/fire-fatality-corrected.csv from the U.S. Census Bureau API.

For each fire x census-place row this pulls sex-by-age counts from TWO sources and
keeps both, flagging one as `preferred`:

  * ACS 5-year  — most recent vintage whose reference period ends before the fire
                  (vintage = fire_year - 1, stepped down if not yet published/tabulated).
                  Sample-based: precise for large places, very noisy for small CDPs.
  * Decennial   — most recent full count on or before the fire (2010 SF1 or 2020 DHC;
                  April 1 reference date, so 2020 counts precede the fall-2020 fires).
                  A full enumeration: the reliable choice for small places, at the cost
                  of being up to ten years stale (and mild 2020 DAS noise).

Preference rule (documented, adjustable): places with a decennial population below
SMALL_PLACE_THRESHOLD (5,000) prefer the decennial count — ACS age-bin margins of
error routinely exceed the estimate itself at that size — while larger places prefer
the fresher ACS estimate. Whichever source is unavailable cedes to the other.

Some census places were only first tabulated in 2020 (e.g. Moskowite Corner CDP,
Silverado Resort CDP). For pre-2020 fires in those places the only data available is
post-fire; the row is kept and `match_note` says so.

Age bins: the census 23-bin sex-by-age table is collapsed to decades 0–9 … 70–79
plus a terminal 80+ (the census tops out at 85+, so 80–89/90–99/100+ cannot be
separated; collapse the notebook baseline's last three bands to compare).

Idempotent and cache-first: every API response is stored under data/raw/census/ and
re-runs are fully offline once the cache is populated. Output CSV is deterministic.

Run from the repo root (network to api.census.gov required on first run; an optional
CENSUS_API_KEY env var raises the rate limit but is not needed at this volume):

    python scripts/fetch_community_age_structure.py            # fetch + write CSV
    python scripts/fetch_community_age_structure.py --plan     # no network: show what would be fetched
    python scripts/fetch_community_age_structure.py --self-test  # no network: check the bin math

Writes: data/community-age-structure.csv   (long/tidy, keyed on Fire + census_place,
so it left-joins onto data/fire-fatality-corrected.csv; scripts/merge_fire_data.py
does exactly that.)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CORRECTED = ROOT / "data" / "fire-fatality-corrected.csv"
SD01 = ROOT / "study" / "data" / "pnas.2535081123.sd01.xlsx"
CACHE = ROOT / "data" / "raw" / "census"
OUT = ROOT / "data" / "community-age-structure.csv"

SMALL_PLACE_THRESHOLD = 5_000  # below this decennial pop, prefer decennial over ACS
ACS_FLOOR = 2009               # first ACS 5-year vintage
ACS_CEILING = 2023             # newest vintage to probe (bump when new releases land)

BANDS = ["0–9", "10–19", "20–29", "30–39", "40–49", "50–59", "60–69", "70–79", "80+"]

# The 49-cell sex-by-age layout shared by ACS B01001, 2010 SF1 P12 and 2020 DHC P12:
# cell 1 total, 2 male total, 3-25 male age bins, 26 female total, 27-49 female bins.
_MALE_BIN_TO_BAND = {
    3: "0–9", 4: "0–9",
    5: "10–19", 6: "10–19", 7: "10–19",
    8: "20–29", 9: "20–29", 10: "20–29", 11: "20–29",
    12: "30–39", 13: "30–39",
    14: "40–49", 15: "40–49",
    16: "50–59", 17: "50–59",
    18: "60–69", 19: "60–69", 20: "60–69", 21: "60–69",
    22: "70–79", 23: "70–79",
    24: "80+", 25: "80+",
}
CELL_TO_BAND = {**_MALE_BIN_TO_BAND, **{k + 24: v for k, v in _MALE_BIN_TO_BAND.items()}}

# census_place values (as spelled in fire-fatality-corrected.csv) that need help
# resolving to a real census place. Everything else defaults to California and
# fuzzy suffix-insensitive name matching.
#   name  = canonical place name to match in the census place list
#   state = 2-digit state FIPS
#   note  = carried into the output's match_note column
OVERRIDES: dict[str, dict] = {
    "Lahiaina": {"name": "Lahaina CDP", "state": "15"},
    "Gatlinburg": {"name": "Gatlinburg city", "state": "47"},
    "Manitou": {
        "name": "Manitou Springs city", "state": "08",
        "note": "authors' population (235) does not match Manitou Springs (~5,300); "
                "the two Waldo Canyon deaths were in the Mountain Shadows area of "
                "Colorado Springs — treat these shares with care",
    },
    "Weed City": {"name": "Weed city", "state": "06"},
    "Hidden Valley Lake CDP, California": {"name": "Hidden Valley Lake CDP", "state": "06"},
    "Silvarado Resort": {
        "name": "Silverado Resort CDP", "state": "06",
        "note": "first tabulated as a CDP in 2020, after the 2017 Atlas fire; "
                "all available age data is post-fire",
    },
    "Klamath CDP": {
        "name": "Klamath River CDP", "state": "06",
        "note": "authors' 'Klamath CDP' (pop 946) is the Del Norte County place ~60 mi "
                "from the fire; the four McKinney deaths were in the Klamath River "
                "community (Siskiyou Co.), used here instead",
    },
    "Walker": {"name": "Walker CDP", "state": "06"},
}

STATE_NAMES = {"06": "California", "08": "Colorado", "15": "Hawaii", "47": "Tennessee"}


# ---------------------------------------------------------------- fetching
def _fetch(url: str, tries: int = 4) -> list:
    key = os.environ.get("CENSUS_API_KEY")
    if key:
        url += ("&" if "?" in url else "?") + "key=" + key
    last: Exception | None = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise  # dataset/vintage doesn't exist — caller handles fallback
            last = e
        except Exception as e:  # transient network errors
            last = e
        time.sleep(2 ** i)
    raise RuntimeError(f"census API failed after {tries} tries: {url}\n{last}")


def _cached(name: str, url: str) -> list:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{name}.json"
    if f.exists():
        return json.loads(f.read_text())
    data = _fetch(url)
    f.write_text(json.dumps(data))
    return data


class Dataset:
    """One census dataset (acs5-2019, dec-2010, dec-2020) for one state."""

    def __init__(self, kind: str, vintage: int, state: str):
        self.kind, self.vintage, self.state = kind, vintage, state
        if kind == "acs5":
            self.base = f"https://api.census.gov/data/{vintage}/acs/acs5"
        elif (kind, vintage) == ("dec", 2010):
            self.base = "https://api.census.gov/data/2010/dec/sf1"
        elif (kind, vintage) == ("dec", 2020):
            self.base = "https://api.census.gov/data/2020/dec/dhc"
        else:
            raise ValueError(f"unsupported dataset {kind} {vintage}")

    @property
    def label(self) -> str:
        return f"{self.kind}-{self.vintage}"

    def _cell_var(self, i: int) -> str:
        if self.kind == "acs5":
            return f"B01001_{i:03d}E"
        if self.vintage == 2010:
            return f"P{12:03d}{i:03d}"  # P012001 …
        return f"P12_{i:03d}N"          # 2020 DHC

    def places(self) -> dict[str, str]:
        """fips -> NAME for every place in the state (cached)."""
        url = f"{self.base}?get=NAME&for=place:*&in=state:{self.state}"
        data = _cached(f"placelist_{self.label}_{self.state}", url)
        hdr = data[0]
        i_name, i_pl = hdr.index("NAME"), hdr.index("place")
        return {row[i_pl]: row[i_name] for row in data[1:]}

    def age_counts(self, place_fips: str) -> dict:
        """Return {'total', 'total_moe', 'bands': {band: pop}, 'bands_moe': {band: moe}}."""
        if self.kind == "acs5":
            get = "group(B01001)"
        else:
            get = ",".join(self._cell_var(i) for i in range(1, 50))
        url = f"{self.base}?get={get}&for=place:{place_fips}&in=state:{self.state}"
        data = _cached(f"age_{self.label}_{self.state}_{place_fips}", url)
        hdr, row = data[0], data[1]
        val = dict(zip(hdr, row))

        def num(v):  # ACS uses negative sentinels / None for suppressed cells
            try:
                x = float(v)
            except (TypeError, ValueError):
                return 0.0
            return x if x >= 0 else 0.0

        bands = {b: 0.0 for b in BANDS}
        bands_var = {b: 0.0 for b in BANDS}  # sum of squared MOEs
        for i, band in CELL_TO_BAND.items():
            bands[band] += num(val.get(self._cell_var(i)))
            if self.kind == "acs5":
                bands_var[band] += num(val.get(f"B01001_{i:03d}M")) ** 2
        out = {
            "total": num(val.get(self._cell_var(1))),
            "total_moe": num(val.get("B01001_001M")) if self.kind == "acs5" else 0.0,
            "bands": bands,
            "bands_moe": {b: math.sqrt(v) for b, v in bands_var.items()},
        }
        return out


# ---------------------------------------------------------------- matching
def _norm(name: str) -> str:
    s = name.lower()
    s = re.sub(r",\s*(california|hawaii|tennessee|colorado)$", "", s)
    s = re.sub(r"\b(cdp|city|town|village)\b", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def resolve_place(raw: str, places: dict[str, str]) -> tuple[str | None, str | None, str]:
    """-> (fips, matched_name, note). Exact normalized match, else best fuzzy >= 0.90."""
    want = _norm(raw)
    exact = [(f, n) for f, n in places.items() if _norm(n) == want]
    if len(exact) == 1:
        return exact[0][0], exact[0][1], ""
    if len(exact) > 1:  # e.g. a city and a CDP sharing a name — prefer the CDP spelling given
        for f, n in exact:
            if ("CDP" in n) == ("CDP" in raw):
                return f, n, "multiple exact matches; picked by CDP/city suffix"
        return exact[0][0], exact[0][1], "multiple exact matches; picked first"
    best, score = None, 0.0
    for f, n in places.items():
        r = SequenceMatcher(None, want, _norm(n)).ratio()
        if r > score:
            best, score = (f, n), r
    if best and score >= 0.90:
        return best[0], best[1], f"fuzzy match ({score:.2f})"
    return None, None, f"no match (closest: {best[1] if best else '—'} {score:.2f})"


# ---------------------------------------------------------------- driver
def load_driver() -> pd.DataFrame:
    fires = pd.read_csv(CORRECTED)
    years = (
        pd.ExcelFile(SD01).parse("redbooks + top 20 fires")[["Fire", "Year"]]
        .dropna().drop_duplicates("Fire").set_index("Fire")["Year"].astype(int)
    )
    fires["fire_year"] = fires["Fire"].map(years)
    missing = fires[fires["fire_year"].isna()]
    if len(missing):
        sys.exit(f"no Year found in sd01 for fires: {missing['Fire'].tolist()}")
    fires["fire_year"] = fires["fire_year"].astype(int)
    return fires[["Fire", "census_place", "fire_year"]]


def plan_row(place_raw: str, fire_year: int) -> dict:
    ov = OVERRIDES.get(place_raw, {})
    return {
        "query_name": ov.get("name", place_raw),
        "state": ov.get("state", "06"),
        "note": ov.get("note", ""),
        "acs_vintage": max(ACS_FLOOR, min(fire_year - 1, ACS_CEILING)),
        "dec_vintage": 2020 if fire_year >= 2020 else 2010,
    }


def acs_dataset(vintage: int, state: str) -> Dataset | None:
    """Newest ACS vintage <= requested that actually exists, stepping down on 404."""
    for v in range(vintage, ACS_FLOOR - 1, -1):
        ds = Dataset("acs5", v, state)
        try:
            ds.places()
            return ds
        except urllib.error.HTTPError:
            continue
    return None


def collect() -> pd.DataFrame:
    fires = load_driver()
    rows: list[dict] = []
    warnings: list[str] = []

    for _, fr in fires.iterrows():
        p = plan_row(fr["census_place"], fr["fire_year"])
        sources: list[tuple[Dataset, str, str, str]] = []  # (ds, fips, matched, note)

        for kind in ("dec", "acs5"):
            if kind == "dec":
                ds = Dataset("dec", p["dec_vintage"], p["state"])
                fips, matched, mnote = resolve_place(p["query_name"], ds.places())
                if fips is None and p["dec_vintage"] == 2010:
                    # place first tabulated in 2020 — post-fire fallback
                    ds = Dataset("dec", 2020, p["state"])
                    fips, matched, mnote = resolve_place(p["query_name"], ds.places())
                    if fips is not None:
                        mnote = (mnote + "; " if mnote else "") + \
                            "not tabulated in 2010; 2020 count is post-fire"
            else:
                ds = acs_dataset(p["acs_vintage"], p["state"])
                if ds is None:
                    continue
                fips, matched, mnote = resolve_place(p["query_name"], ds.places())
                if fips is None:
                    # step forward: some CDPs only enter ACS tabulation in later vintages
                    for v in range(ds.vintage + 1, ACS_CEILING + 1):
                        ds2 = acs_dataset(v, p["state"])
                        if ds2 is None or ds2.vintage != v:
                            continue
                        fips, matched, mnote = resolve_place(p["query_name"], ds2.places())
                        if fips is not None:
                            ds = ds2
                            mnote = (mnote + "; " if mnote else "") + \
                                f"only tabulated from vintage {v} (post-fire)"
                            break
            if fips is None:
                warnings.append(f"{fr['Fire']} / {fr['census_place']}: {ds.label}: {mnote}")
                continue
            sources.append((ds, fips, matched, mnote))

        if not sources:
            warnings.append(f"{fr['Fire']} / {fr['census_place']}: NO census place matched at all")
            continue

        counts = {ds.label: ds.age_counts(fips) for ds, fips, _, _ in sources}
        dec_total = next(
            (counts[ds.label]["total"] for ds, *_ in sources if ds.kind == "dec"), None
        )
        have_kinds = {ds.kind for ds, *_ in sources}
        prefer_kind = (
            "dec" if ("dec" in have_kinds and
                      ("acs5" not in have_kinds or (dec_total or 0) < SMALL_PLACE_THRESHOLD))
            else "acs5"
        )

        for ds, fips, matched, mnote in sources:
            c = counts[ds.label]
            note = "; ".join(x for x in (p["note"], mnote) if x)
            for band in BANDS:
                pop, moe = c["bands"][band], c["bands_moe"][band]
                total, tmoe = c["total"], c["total_moe"]
                share = 100 * pop / total if total else float("nan")
                if ds.kind == "acs5" and total:
                    share_moe = 100 / total * math.sqrt(
                        max(moe**2 - (pop / total) ** 2 * tmoe**2, 0)
                    )
                else:
                    share_moe = 0.0
                rows.append({
                    "Fire": fr["Fire"], "census_place": fr["census_place"],
                    "fire_year": fr["fire_year"], "state_fips": p["state"],
                    "place_fips": fips, "matched_place_name": matched,
                    "dataset": ds.label, "decade_band": band,
                    "pop": round(pop), "pop_moe": round(moe, 1),
                    "share_pct": round(share, 3), "share_moe_pct": round(share_moe, 3),
                    "total_pop": round(c["total"]), "total_pop_moe": round(tmoe, 1),
                    "preferred": ds.kind == prefer_kind, "match_note": note,
                })

    df = pd.DataFrame(rows)
    df["decade_band"] = pd.Categorical(df["decade_band"], categories=BANDS, ordered=True)
    df = df.sort_values(["Fire", "census_place", "dataset", "decade_band"]).reset_index(drop=True)
    if warnings:
        print("WARNINGS:", file=sys.stderr)
        for w in warnings:
            print("  " + w, file=sys.stderr)
    return df


# ---------------------------------------------------------------- modes
def self_test() -> None:
    """Check the 49-cell -> decade-band collapse on a synthetic vector."""
    assert len(CELL_TO_BAND) == 46 and set(CELL_TO_BAND.values()) == set(BANDS)
    # cell value = cell index; band sums must equal sum of male+female cell indices
    fake = {i: float(i) for i in range(1, 50)}
    got = {b: 0.0 for b in BANDS}
    for i, b in CELL_TO_BAND.items():
        got[b] += fake[i]
    assert got["0–9"] == (3 + 4) + (27 + 28)
    assert got["80+"] == (24 + 25) + (48 + 49)
    assert sum(got.values()) == sum(range(3, 26)) + sum(range(27, 50))
    v10 = Dataset("dec", 2010, "06")
    v20 = Dataset("dec", 2020, "06")
    acs = Dataset("acs5", 2019, "06")
    assert v10._cell_var(3) == "P012003"
    assert v20._cell_var(49) == "P12_049N"
    assert acs._cell_var(1) == "B01001_001E"
    assert _norm("Hidden Valley Lake CDP, California") == _norm("Hidden Valley Lake CDP")
    assert _norm("Weed city") == _norm("Weed City")
    print("self-test OK")


def show_plan() -> None:
    fires = load_driver()
    for _, fr in fires.iterrows():
        p = plan_row(fr["census_place"], fr["fire_year"])
        print(f"{fr['Fire']:<35} {fr['census_place']:<36} -> {p['query_name']} "
              f"[{STATE_NAMES[p['state']]}]  acs5-{p['acs_vintage']}  dec-{p['dec_vintage']}"
              + (f"  ({p['note']})" if p["note"] else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true", help="show fetch plan, no network")
    ap.add_argument("--self-test", action="store_true", help="run offline checks")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.plan:
        return show_plan()
    df = collect()
    df.to_csv(OUT, index=False)
    n_places = df.groupby(["Fire", "census_place"]).ngroups
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(df)} rows, {n_places} fire x place "
          f"communities, {df['dataset'].nunique()} census sources)")


if __name__ == "__main__":
    main()
