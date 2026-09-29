"""In-memory spatial index of fuel stations, and route -> candidate station matching."""
import threading
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from . import geo

_lock = threading.Lock()
_index = None


@dataclass
class StationIndex:
    ids: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    price: np.ndarray
    xyz: np.ndarray
    meta: list  # dicts with name/address/city/state per row

    @classmethod
    def from_db(cls):
        from fuel_planner.models import FuelStation

        rows = list(
            FuelStation.objects.values_list(
                "opis_id", "latitude", "longitude", "retail_price", "name", "address", "city", "state"
            )
        )
        if not rows:
            raise RuntimeError("No fuel stations loaded. Run `python manage.py load_stations`.")
        ids, lat, lon, price, *_ = zip(*rows)
        lat, lon = np.array(lat), np.array(lon)
        return cls(
            ids=np.array(ids),
            lat=lat,
            lon=lon,
            price=np.array(price, dtype=float),
            xyz=geo.to_unit_xyz(lat, lon),
            meta=[{"name": r[4], "address": r[5], "city": r[6], "state": r[7]} for r in rows],
        )


def get_index() -> StationIndex:
    """Loaded once per process (~6k rows, a few ms), then reused by every request."""
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                _index = StationIndex.from_db()
    return _index


def reset_index():
    global _index
    _index = None


@dataclass
class Candidates:
    rows: np.ndarray  # indices into the StationIndex, sorted by route mile
    route_mile: np.ndarray
    off_route_miles: np.ndarray


def stations_along_route(coords, route_distance_miles, max_detour_miles, index=None, sample_step_mi=0.5):
    """Stations within `max_detour_miles` of the route, with their mile marker along it.

    The route is resampled every `sample_step_mi`, put in a KD-tree on the unit
    sphere, and every station (pre-filtered by bounding box) is matched to its
    nearest route sample in one vectorised query.
    """
    index = index or get_index()
    pts = np.asarray(coords, dtype=float)
    lats, lons, miles = geo.resample_polyline(pts[:, 1], pts[:, 0], sample_step_mi)
    # Our haversine length differs slightly from OSRM's road distance; rescale
    # so mile markers are consistent with the reported trip distance.
    if miles[-1] > 0:
        miles = miles * (route_distance_miles / miles[-1])

    pad_lat = max_detour_miles / 69.0
    pad_lon = max_detour_miles / (69.0 * max(np.cos(np.radians(np.abs(lats).max())), 0.2))
    in_box = np.flatnonzero(
        (index.lat >= lats.min() - pad_lat) & (index.lat <= lats.max() + pad_lat)
        & (index.lon >= lons.min() - pad_lon) & (index.lon <= lons.max() + pad_lon)
    )
    if in_box.size == 0:
        return Candidates(np.array([], int), np.array([]), np.array([]))

    tree = cKDTree(geo.to_unit_xyz(lats, lons))
    chord, nearest = tree.query(index.xyz[in_box], distance_upper_bound=float(geo.miles_to_chord(max_detour_miles)))
    ok = np.isfinite(chord)
    rows, nearest, chord = in_box[ok], nearest[ok], chord[ok]
    route_mile = miles[nearest]
    off = geo.chord_to_miles(chord)

    order = np.lexsort((index.price[rows], route_mile))
    return Candidates(rows[order], route_mile[order], off[order])
