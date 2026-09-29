"""Resolve free-text start/finish inputs to coordinates inside the USA.

Resolution order (cheapest first):
  1. "lat,lon" literal                     -> no external call
  2. "City, ST" / "City, State"            -> offline Census gazetteer, no external call
  3. anything else (street address, ZIP)   -> Nominatim, cached
"""
import re
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from . import gazetteer


class GeocodingError(ValueError):
    pass


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    label: str
    source: str

    def as_dict(self):
        return {"query_label": self.label, "lat": self.lat, "lon": self.lon, "geocoded_by": self.source}


_LATLON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

# Rough bounding boxes: contiguous US, Alaska, Hawaii.
_US_BOXES = [(24.3, 49.5, -125.0, -66.8), (51.0, 71.5, -179.9, -129.9), (18.8, 22.4, -160.5, -154.7)]


def in_usa(lat: float, lon: float) -> bool:
    return any(s <= lat <= n and w <= lon <= e for s, n, w, e in _US_BOXES)


def resolve(text: str) -> Location:
    text = (text or "").strip()
    if not text:
        raise GeocodingError("Location is empty.")

    m = _LATLON.match(text)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if not in_usa(lat, lon):
            raise GeocodingError(f"'{text}' is not inside the USA (expected 'lat,lon').")
        return Location(lat, lon, text, "coordinates")

    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) == 3 and parts[2].upper() in ("USA", "US", "UNITED STATES"):
        parts = parts[:2]
    if len(parts) == 2 and not any(c.isdigit() for c in text):  # "City, ST"; digits mean a street address
        city, state = parts
        code = gazetteer.normalize_state(state)
        if not code:
            raise GeocodingError(f"'{state}' in '{text}' is not a US state (expected 'City, ST').")
        hit = gazetteer.lookup(city, code)
        if hit:
            lat, lon, name = hit
            return Location(lat, lon, f"{name}, {code}", "census_gazetteer")
        # Structured search, so an unknown city can't fuzzy-match a street elsewhere.
        return nominatim(text, {"city": city, "state": gazetteer.US_STATES[code]})

    return nominatim(text)


def nominatim(query: str, structured: dict | None = None) -> Location:
    key = "nominatim:" + re.sub(r"\s+", " ", query.lower()) + (":structured" if structured else "")
    cached = cache.get(key)
    if cached:
        return Location(**cached)
    try:
        resp = requests.get(
            settings.NOMINATIM_URL,
            params={**(structured or {"q": query}), "format": "jsonv2", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": settings.HTTP_USER_AGENT},
            timeout=settings.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        results = resp.json()
    except requests.RequestException as exc:
        raise GeocodingError(f"Geocoding service unavailable: {exc}") from exc
    if not results:
        raise GeocodingError(f"Could not find '{query}' in the USA.")
    r = results[0]
    loc = Location(float(r["lat"]), float(r["lon"]), r.get("display_name", query), "nominatim")
    cache.set(key, loc.__dict__)
    return loc
