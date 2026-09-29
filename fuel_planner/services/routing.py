"""Driving route from a free public OSRM server: one HTTP call per route, cached.

The OSRM demo server is best-effort and occasionally slow, so a second free
OSRM host (FOSSGIS, same API) is tried only if the first one fails.
"""
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from .geo import METERS_PER_MILE, simplify_polyline


class RoutingError(RuntimeError):
    pass


@dataclass
class Route:
    coordinates: list  # [[lon, lat], ...] full resolution
    distance_miles: float
    duration_seconds: float
    simplified: list  # reduced geometry for responses/maps, computed once per route
    from_cache: bool = False


def get_route(start_lat, start_lon, end_lat, end_lon) -> Route:
    coords = f"{start_lon:.5f},{start_lat:.5f};{end_lon:.5f},{end_lat:.5f}"
    key = f"osrm:{coords}"
    cached = cache.get(key)
    if cached:
        return Route(**cached, from_cache=True)

    data, errors = None, []
    for base in settings.OSRM_BASE_URLS:
        try:
            resp = requests.get(
                f"{base}/route/v1/driving/{coords}",
                params={"overview": "full", "geometries": "geojson", "steps": "false", "alternatives": "false"},
                headers={"User-Agent": settings.HTTP_USER_AGENT},
                timeout=settings.HTTP_TIMEOUT_SECONDS,
            )
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{base}: {exc.__class__.__name__}")
            continue
        if data.get("code") == "Ok" and data.get("routes"):
            break
        if data.get("code") in ("NoRoute", "NoSegment", "InvalidInput"):
            raise RoutingError(f"No driving route found ({data['code']}: {data.get('message', '')}).")
        errors.append(f"{base}: {data.get('code')}")
    else:
        raise RoutingError("Routing service unavailable (" + "; ".join(errors) + ").")

    r = data["routes"][0]
    route = Route(
        coordinates=r["geometry"]["coordinates"],
        distance_miles=r["distance"] / METERS_PER_MILE,
        duration_seconds=r["duration"],
        simplified=[[round(x, 5), round(y, 5)] for x, y in simplify_polyline(r["geometry"]["coordinates"])],
    )
    cache.set(key, {k: v for k, v in route.__dict__.items() if k != "from_cache"})
    return route
