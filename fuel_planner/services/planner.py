"""Orchestrates one trip plan: geocode -> route (1 external call) -> stations -> optimise."""
import hashlib
import json
import time

from django.conf import settings
from django.core.cache import cache

from . import geocoding, optimizer, routing, stations


class PlanningError(ValueError):
    """User-facing error (bad input, unroutable trip, no stations in range)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def plan_trip(start: str, finish: str, max_detour_miles: float | None = None, start_tank: str = "empty",
              stop_penalty_usd: float | None = None) -> dict:
    t0 = time.perf_counter()
    max_detour = float(max_detour_miles or settings.DEFAULT_MAX_DETOUR_MILES)
    penalty = float(settings.DEFAULT_STOP_PENALTY_USD if stop_penalty_usd is None else stop_penalty_usd)
    key = "plan:" + hashlib.sha1(
        json.dumps([start.strip().lower(), finish.strip().lower(), max_detour, start_tank, penalty]).encode()
    ).hexdigest()
    cached = cache.get(key)
    if cached:
        cached["meta"] = {"cached_plan": True, "external_api_calls": 0, "compute_ms": _ms(t0)}
        return cached

    calls = 0
    try:
        origin = geocoding.resolve(start)
        dest = geocoding.resolve(finish)
    except geocoding.GeocodingError as exc:
        raise PlanningError(str(exc)) from exc
    calls += (origin.source == "nominatim") + (dest.source == "nominatim")  # upper bound; may be cached
    t_geo = time.perf_counter()

    try:
        route = routing.get_route(origin.lat, origin.lon, dest.lat, dest.lon)
    except routing.RoutingError as exc:
        raise PlanningError(str(exc), status=502) from exc
    calls += not route.from_cache
    t_route = time.perf_counter()

    rng, mpg = settings.VEHICLE_RANGE_MILES, settings.VEHICLE_MPG
    index = stations.get_index()
    cand = stations.stations_along_route(route.coordinates, route.distance_miles, max_detour, index)
    positions = cand.route_mile.tolist()
    prices = index.price[cand.rows].tolist()

    try:
        fuel_plan = optimizer.plan_practical(
            positions, prices, route.distance_miles, rng, mpg, start_tank,
            stop_penalty=penalty, detour_miles=cand.off_route_miles.tolist(),
        )
    except optimizer.InfeasibleRoute as exc:
        raise PlanningError(
            f"{exc}. The vehicle range is {rng} mi and only stations within {max_detour:g} mi of the "
            "route are considered; try a larger max_detour_miles.",
            status=422,
        ) from exc

    stops = []
    for n, p in enumerate(fuel_plan.purchases, 1):
        row = int(cand.rows[p.station])
        gallons = p.miles_of_fuel / mpg
        stops.append({
            "stop_number": n,
            "opis_id": int(index.ids[row]),
            **index.meta[row],
            "lat": round(float(index.lat[row]), 6),
            "lon": round(float(index.lon[row]), 6),
            "price_per_gallon": round(prices[p.station], 3),
            "route_mile": round(positions[p.station], 1),
            "off_route_miles": round(float(cand.off_route_miles[p.station]), 1),
            "gallons": round(gallons, 2),
            "cost": round(gallons * prices[p.station], 2),
        })

    total_cost = fuel_plan.cost(prices, mpg)
    purchased_gallons = sum(p.miles_of_fuel for p in fuel_plan.purchases) / mpg
    initial = None
    if fuel_plan.initial_fuel_billed_station is not None:
        g = fuel_plan.initial_fuel_miles / mpg
        pr = prices[fuel_plan.initial_fuel_billed_station]
        initial = {
            "gallons": round(g, 2),
            "valued_at_price": round(pr, 3),
            "cost": round(g * pr, 2),
            "note": "Fuel used to reach the first station on the route, valued at that station's price.",
        }
    billed_gallons = purchased_gallons + (fuel_plan.initial_fuel_miles / mpg if initial else 0)

    result = {
        "start": origin.as_dict(),
        "finish": dest.as_dict(),
        "route": {
            "distance_miles": round(route.distance_miles, 1),
            "duration_hours": round(route.duration_seconds / 3600, 2),
            "geometry": {"type": "LineString", "coordinates": route.simplified},
        },
        "fuel_stops": stops,
        "summary": {
            "total_fuel_cost": round(total_cost, 2),
            "total_gallons": round(billed_gallons, 2),
            "gallons_purchased_at_stops": round(purchased_gallons, 2),
            "average_price_per_gallon": round(total_cost / billed_gallons, 3) if billed_gallons else None,
            "number_of_stops": len(stops),
            "initial_fuel": initial,
            "assumptions": {
                "mpg": mpg,
                "tank_range_miles": rng,
                "start_tank": start_tank,
                "max_detour_miles": max_detour,
                "stop_penalty_usd": penalty,
                "stations_considered": len(positions),
            },
        },
    }
    cache.set(key, result)
    result["meta"] = {
        "cached_plan": False,
        "external_api_calls": calls,
        "route_from_cache": route.from_cache,
        "compute_ms": _ms(t0),
        "timings_ms": {
            "geocoding": round((t_geo - t0) * 1000, 1),
            "routing_api": round((t_route - t_geo) * 1000, 1),
            "stations_and_optimisation": _ms(t_route),
        },
    }
    return result


def to_geojson(plan: dict) -> dict:
    """Route + stops as a GeoJSON FeatureCollection (paste into geojson.io to view)."""
    feats = [{"type": "Feature", "geometry": plan["route"]["geometry"],
              "properties": {"kind": "route", "distance_miles": plan["route"]["distance_miles"]}}]
    for kind in ("start", "finish"):
        p = plan[kind]
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                      "properties": {"kind": kind, "label": p["query_label"]}})
    for s in plan["fuel_stops"]:
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                      "properties": {"kind": "fuel_stop", **{k: v for k, v in s.items() if k not in ("lat", "lon")}}})
    return {"type": "FeatureCollection", "features": feats}


def _ms(t0):
    return round((time.perf_counter() - t0) * 1000, 1)
