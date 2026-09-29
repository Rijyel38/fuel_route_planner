"""Small, dependency-light geometry helpers (all distances in miles)."""
import numpy as np

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344


def haversine_mi(lat1, lon1, lat2, lon2):
    """Vectorised great-circle distance in miles."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MI * np.arcsin(np.sqrt(a))


def to_unit_xyz(lat, lon):
    """Lat/lon (degrees) -> points on the unit sphere, for KD-tree lookups."""
    lat, lon = np.radians(lat), np.radians(lon)
    cos_lat = np.cos(lat)
    return np.column_stack((cos_lat * np.cos(lon), cos_lat * np.sin(lon), np.sin(lat)))


def miles_to_chord(miles):
    """Great-circle distance in miles -> straight-line chord on the unit sphere."""
    return 2 * np.sin(np.asarray(miles) / (2 * EARTH_RADIUS_MI))


def chord_to_miles(chord):
    return 2 * EARTH_RADIUS_MI * np.arcsin(np.clip(np.asarray(chord) / 2, 0, 1))


def cumulative_miles(lats, lons):
    """Cumulative distance along a polyline, starting at 0."""
    seg = haversine_mi(lats[:-1], lons[:-1], lats[1:], lons[1:])
    return np.concatenate(([0.0], np.cumsum(seg)))


def resample_polyline(lats, lons, step_mi):
    """Points every `step_mi` miles along a polyline, plus the cumulative mile of each.

    OSRM geometry is dense on curves but can be sparse on long straight
    interstates; uniform resampling keeps nearest-vertex distance errors bounded.
    """
    cum = cumulative_miles(lats, lons)
    total = cum[-1]
    if total == 0:
        return lats[:1], lons[:1], np.zeros(1)
    samples = np.append(np.arange(0.0, total, step_mi), total)
    return np.interp(samples, cum, lats), np.interp(samples, cum, lons), samples


def simplify_polyline(coords, tolerance_deg=0.0005):
    """Ramer-Douglas-Peucker simplification of [[lon, lat], ...] (iterative, vectorised).

    Only used to keep the response payload small; the full-resolution geometry
    is still used for all distance calculations.
    """
    pts = np.asarray(coords, dtype=float)
    n = len(pts)
    if n < 3:
        return pts.tolist()
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue
        a, b = pts[start], pts[end]
        seg = pts[start + 1 : end]
        ab = b - a
        norm = np.hypot(*ab)
        if norm == 0:
            dists = np.hypot(*(seg - a).T)
        else:
            dists = np.abs(ab[0] * (seg[:, 1] - a[1]) - ab[1] * (seg[:, 0] - a[0])) / norm
        idx = int(np.argmax(dists))
        if dists[idx] > tolerance_deg:
            mid = start + 1 + idx
            keep[mid] = True
            stack.append((start, mid))
            stack.append((mid, end))
    return pts[keep].tolist()
