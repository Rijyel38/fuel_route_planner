# Fuel Route Planner (Django)

An API that takes a start and finish location in the USA and returns:

- the driving route (GeoJSON geometry, plus an interactive map page),
- the fuel stops that make the trip cheapest, for a vehicle with a **500-mile range** at **10 mpg**,
- how much fuel to buy at each stop and the **total fuel cost**.

It makes **one call to the routing API per new trip**. Start/finish in "City, ST" or "lat,lon" form are resolved offline, and repeat requests hit no external API at all.

| Trip | Distance | Stops | Fuel cost | First request | Cached |
|---|---|---|---|---|---|
| New York, NY → Los Angeles, CA | 2,810 mi | 7 | $866.25 | ~3.6 s (3.5 s is the OSRM call) | ~20 ms |
| Seattle, WA → Miami, FL | 3,303 mi | 8 | $1,042.90 | ~3.9 s (3.8 s is the OSRM call) | ~20 ms |

Excluding the routing call, all local work (station matching and optimisation) takes about 100 ms. Timings are measured locally against the public OSRM demo server.

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py load_stations    # loads the pre-geocoded stations (committed in data/)
python manage.py runserver
```

- API: `http://127.0.0.1:8000/api/route/?start=New York, NY&finish=Los Angeles, CA`
- Map: `http://127.0.0.1:8000/` (form), or the `map.html_url` returned by the API
- Tests: `python manage.py test fuel_planner`

Requires Python 3.12+ (developed on 3.14) and Django 6.1.

## API

### `GET /api/route/` or `POST /api/route/`

| Field | Required | Default | Notes |
|---|---|---|---|
| `start`, `finish` | yes | | `"City, ST"` (offline), `"lat,lon"` (offline), or any US address (Nominatim) |
| `max_detour_miles` | no | `10` | How far from the route a station may be |
| `stop_penalty_usd` | no | `10` | Cost per stop used when *choosing* stops (driver time). `0` = cheapest fuel regardless of how many stops |
| `start_tank` | no | `"empty"` | `"empty"`: the cost covers every mile of the trip. `"full"`: leave with a free full tank |

```bash
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "New York, NY", "finish": "Los Angeles, CA"}'
```

Response (abridged):

```json
{
  "start":  {"query_label": "New York, NY", "lat": 40.66, "lon": -73.94, "geocoded_by": "census_gazetteer"},
  "finish": {"query_label": "Los Angeles, CA", "lat": 34.02, "lon": -118.41, "geocoded_by": "census_gazetteer"},
  "route": {
    "distance_miles": 2810.4,
    "duration_hours": 50.31,
    "geometry": {"type": "LineString", "coordinates": [[-73.94, 40.66], "..."]}
  },
  "fuel_stops": [
    {"stop_number": 1, "opis_id": 72087, "name": "DELTA", "address": "US-9", "city": "Jersey City", "state": "NJ",
     "lat": 40.711, "lon": -74.064, "price_per_gallon": 3.239, "route_mile": 9.0,
     "off_route_miles": 1.6, "gallons": 39.61, "cost": 128.3},
    {"stop_number": 2, "name": "SHEETZ #791", "city": "North Jackson", "state": "OH", "route_mile": 405.1, "...": "..."}
  ],
  "summary": {
    "total_fuel_cost": 866.25,
    "total_gallons": 281.04,
    "average_price_per_gallon": 3.082,
    "number_of_stops": 7,
    "initial_fuel": {"gallons": 0.9, "valued_at_price": 3.239, "cost": 2.92},
    "assumptions": {"mpg": 10, "tank_range_miles": 500, "start_tank": "empty",
                    "max_detour_miles": 10.0, "stop_penalty_usd": 10.0, "stations_considered": 459}
  },
  "map": {"html_url": "http://127.0.0.1:8000/api/route/map/?...", "geojson_url": "http://127.0.0.1:8000/api/route/geojson/?..."},
  "meta": {"cached_plan": false, "external_api_calls": 1,
           "timings_ms": {"geocoding": 1.6, "routing_api": 3497.5, "stations_and_optimisation": 95.3}}
}
```

Errors return `{"error": ...}` with status `400` (bad input or a location outside the USA), `422` (a stretch longer than 500 miles has no station), or `502` (routing service down).

### Other endpoints

- `GET /api/route/map/?start=…&finish=…`: interactive Leaflet map with the route, stops and a cost summary.
- `GET /api/route/geojson/?start=…&finish=…`: the same plan as a GeoJSON FeatureCollection. You can paste it into geojson.io.

Both reuse the cached plan, so opening the map after calling the API costs no extra routing call.

## How it works

```
start/finish ──► geocode (offline gazetteer; Nominatim only for street addresses)
             ──► OSRM route  ◄── the single external call, cached on disk
             ──► stations near the route (KD-tree, ~20 ms)
             ──► choose stops (exact DP, ~25 ms) ──► size each purchase (optimal greedy)
```

### 1. Station data: `fuel_planner/management/commands/build_stations.py`

The price file has no coordinates, and addresses like `I-44, EXIT 283 & US-69` don't geocode reliably. Calling a geocoder per request would also break the "few API calls" requirement. So geocoding runs once, offline:

- Rows are grouped by OPIS ID: 8,151 rows become 6,738 stations. Many stations list several prices; the **lowest** is used.
- Each station is placed at its city's centroid from the **US Census Gazetteer** (places, then county subdivisions for New England towns and townships). City names are normalised so that `Saint Johns` = `St. Johns`, `Mc Calla` = `McCalla`, `Cañon City` = `Canon City`, and `Boise` = `Boise City`.
- The 2.5% the gazetteer can't match fall back to Nominatim (rate limited and cached in `data/raw/nominatim_cache.json`). Result: 6,615 of 6,626 US stations geocoded (6,457 from Census, 158 from Nominatim). The 11 that couldn't be placed are left out.
- 112 Canadian stations are excluded, since the trip must be in the USA.

The output, `data/stations_geocoded.csv`, is committed, so reviewers only run `load_stations`. `data/us_places.csv` (the pre-normalised gazetteer) is also committed and is what makes "City, ST" inputs resolve with no API call.

### 2. Route: `fuel_planner/services/routing.py`

One request to the free public **OSRM** server, with `overview=full` and GeoJSON geometry. If it fails, the free FOSSGIS OSRM mirror is tried; that is the only case where a second call happens. Responses are cached on disk by coordinates.

### 3. Stations along the route: `fuel_planner/services/stations.py`

- The route is resampled every 0.5 mi, so long straight interstates don't have gaps, and loaded into a `scipy` KD-tree on the unit sphere.
- Stations are pre-filtered by bounding box, then matched to the nearest route point in one vectorised query. This gives each station's **mile marker** along the route and its **off-route distance**.
- The station index is loaded from the database once per process and warmed at server start.

### 4. Choosing stops: `fuel_planner/services/optimizer.py`

The problem is the classic "gas station problem": fixed tank, known prices at known mile markers.

- `plan()` is the textbook greedy, which is optimal for pure fuel cost. At each station, if a cheaper one is within range, buy only enough to reach it. Otherwise fill up and go to the cheapest station in range. Tests check it against a brute-force DP on 300 random instances.
- Pure cost-optimal plans are impractical, though. NY→LA took **18 stops**, some buying 0.05 gal to save a cent. `plan_practical()` is therefore an exact DP over (station, fuel level on a 1-mile grid). It charges each stop `stop_penalty_usd` plus the fuel burned on the round trip to an off-route station. The buy step uses a prefix minimum, so it is O(stations × 500) and runs in ~25 ms in numpy.
- The DP chooses *which* stations to stop at. `plan()` then runs on that subset to size each purchase exactly.

With the $10 default, NY→LA uses **7 stops for $866.25**. The same DP with `stop_penalty_usd=0` needs 10 stops for $858.12, and the pure greedy needs 18. That is 1% more on fuel in exchange for 11 fewer stops. Set `stop_penalty_usd=0` to get the pure cheapest plan.

## Assumptions and trade-offs

- **Start tank.** By default the vehicle leaves nearly empty. The small amount of fuel used to reach the first station is valued at that station's price, so `total_fuel_cost` covers every mile of the trip (`total_gallons` = distance / 10). Use `start_tank=full` for the "free full tank" interpretation.
- **Location accuracy.** Stations sit at city centroids, not exact exits, so `off_route_miles` is approximate. The 10-mile default detour allows for this. Big cities are the least precise.
- **Price.** The minimum listed price per station is used. The file doesn't say which listing a driver would actually pay.
- **Detour fuel** is used to choose stops but not added to `total_fuel_cost`, which is reported for the route distance.
- **Free services.** The public OSRM demo is best-effort. For production, point `OSRM_BASE_URLS` at a self-hosted OSRM (see `.env.example`). Nominatim is only used for free-form street addresses.

## Project layout

```
fuel_route_planner/        Django project: settings / urls
fuel_planner/              the app
  models.py                FuelStation
  views.py, serializers.py DRF endpoints + map page
  services/
    geocoding.py           input -> coordinates (offline first)
    gazetteer.py           Census place lookup + name normalisation
    routing.py             OSRM client (cached, with fallback host)
    stations.py            KD-tree station matching
    optimizer.py           greedy + stop-penalty DP
    planner.py             orchestration, response shaping, plan cache
    geo.py                 haversine, resampling, polyline simplification
  management/commands/     build_stations (one-off), load_stations
  templates/fuel_planner/map.html  Leaflet map
  tests/                   optimizer (incl. brute-force check), geocoding, API
data/                      price file, geocoded stations, trimmed gazetteer
```
