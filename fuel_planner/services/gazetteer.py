"""Offline US place lookup ("City, ST" -> lat/lon) built from the Census Gazetteer.

Used for two things:
  * geocoding the fuel stations once (management command `build_stations`);
  * resolving "City, ST" request inputs at runtime without any external call.
"""
import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from django.conf import settings

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
STATE_BY_NAME = {name.lower(): code for code, name in US_STATES.items()}

_PREFIXES = [
    (r"\bst\.?\s+", "saint "),
    (r"\bste\.?\s+", "sainte "),
    (r"\bmt\.?\s+", "mount "),
    (r"\bft\.?\s+", "fort "),
]
# Census names end with a lowercase legal description: "Abbeville city",
# "McCalla CDP", "Nashville-Davidson metropolitan government (balance)".
_LSAD_SUFFIX = re.compile(r"(\s+(\([a-z ]+\)|[a-z]+|CDP|CCD))+$")


def normalize_city(name: str) -> str:
    """Canonical key so 'Saint Johns', 'St. Johns' and 'ST JOHNS' all match."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().strip().lower()
    for pattern, repl in _PREFIXES:
        s = re.sub(pattern, repl, s)
    return re.sub(r"[^a-z0-9]", "", s)


def normalize_state(state: str) -> str | None:
    s = state.strip()
    if s.upper() in US_STATES:
        return s.upper()
    return STATE_BY_NAME.get(s.lower())


def strip_lsad(census_name: str) -> str:
    return _LSAD_SUFFIX.sub("", census_name).strip()


def _aliases(name: str) -> set[str]:
    names = {name}
    # "Nashville-Davidson", "Louisville/Jefferson County" -> also index the parts.
    names.update(p for p in re.split(r"[-/]", name) if len(p) > 2)
    # "Town of Pecos", "City of Oakley" -> "Pecos", "Oakley".
    names.update(re.sub(r"^(Town|City|Village|Borough) of ", "", n) for n in list(names))
    # "Boise City", "Amite City" -> "Boise", "Amite".
    names.update(n[:-5] for n in list(names) if n.endswith(" City") and len(n) > 8)
    return names


def build_places_file(sources: list[tuple[Path, str]], out_csv: Path) -> int:
    """Turn raw Census gazetteers (tab separated) into a ready-to-use lookup table.

    `sources` is [(path, kind)], kind "place" (cities, towns, CDPs) or "cousub"
    (county subdivisions: New England towns, townships). All name aliases are
    normalised here, once, so loading at runtime is just reading rows.
    Ties: an incorporated place beats a county subdivision, then larger land area wins.
    """
    best: dict[tuple[str, str], tuple] = {}
    for path, kind in sources:
        with open(path, encoding="utf-8") as fh:
            for r in csv.DictReader(fh, delimiter="	"):
                r = {k.strip(): (v or "").strip() for k, v in r.items()}
                if r["USPS"] not in US_STATES:
                    continue  # skip Puerto Rico etc.
                name = strip_lsad(r["NAME"])
                if kind == "cousub" and (not name or name[0].isdigit() or "unorganized" in r["NAME"].lower()):
                    continue
                rank = (kind == "place", int(r["ALAND"] or 0))
                for alias in _aliases(name):
                    key = (r["USPS"], normalize_city(alias))
                    if key[1] and (key not in best or rank > best[key][0]):
                        best[key] = (rank, name, r["INTPTLAT"], r["INTPTLONG"])
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["state", "key", "name", "lat", "lon"])
        for (state, key), (_, name, lat, lon) in sorted(best.items()):
            w.writerow([state, key, name, lat, lon])
    return len(best)


@lru_cache(maxsize=1)
def _index() -> dict[tuple[str, str], tuple[float, float, str]]:
    """(state, normalized city) -> (lat, lon, display name)."""
    with open(Path(settings.PLACES_CSV), encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader)
        return {(st, key): (float(lat), float(lon), name) for st, key, name, lat, lon in reader}


def warm():
    _index()


def lookup(city: str, state: str) -> tuple[float, float, str] | None:
    code = normalize_state(state)
    if not code:
        return None
    return _index().get((code, normalize_city(city)))
