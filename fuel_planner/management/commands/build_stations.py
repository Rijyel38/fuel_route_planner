"""One-off data preparation: geocode the OPIS fuel price file.

The price file has no coordinates, and addresses like "I-44, EXIT 283 & US-69"
don't geocode reliably, so each station is placed at its city's Census
centroid. Cities the gazetteer can't match fall back to Nominatim (rate
limited to 1 req/s and cached on disk so re-runs are free).

The output (data/stations_geocoded.csv) is committed, so reviewers only need
`load_stations` and nothing here touches the network at request time.
"""
import csv
import json
import time
from collections import defaultdict
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from fuel_planner.services import gazetteer

GAZETTEER_BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/"
RAW_FILES = [("2024_Gaz_place_national.txt", "place"), ("2024_Gaz_cousubs_national.txt", "cousub")]


class Command(BaseCommand):
    help = "Geocode the fuel price CSV into data/stations_geocoded.csv"

    def add_arguments(self, parser):
        parser.add_argument("--raw-dir", default=str(settings.DATA_DIR / "raw"),
                            help=f"Folder with the unzipped Census gazetteers from {GAZETTEER_BASE}: "
                                 + ", ".join(f for f, _ in RAW_FILES))
        parser.add_argument("--no-nominatim", action="store_true", help="Skip the online fallback.")

    def handle(self, *args, **opts):
        raw_dir = Path(opts["raw_dir"])
        sources = [(raw_dir / f, kind) for f, kind in RAW_FILES]
        if all(p.exists() for p, _ in sources):
            n = gazetteer.build_places_file(sources, settings.PLACES_CSV)
            gazetteer._index.cache_clear()
            self.stdout.write(f"Wrote {n} places to {settings.PLACES_CSV}")
        elif not Path(settings.PLACES_CSV).exists():
            self.stderr.write(f"Need the Census gazetteers in {raw_dir} (from {GAZETTEER_BASE}) or {settings.PLACES_CSV}.")
            return

        stations = self._read_prices()
        cache_path = settings.DATA_DIR / "raw" / "nominatim_cache.json"
        nominatim_cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

        out, stats = [], defaultdict(int)
        for st in stations.values():
            if not gazetteer.normalize_state(st["state"]):
                stats["skipped_non_us"] += 1
                continue
            hit = gazetteer.lookup(st["city"], st["state"])
            source = "census_gazetteer"
            if not hit and not opts["no_nominatim"]:
                hit = self._nominatim(st["city"], st["state"], nominatim_cache)
                source = "nominatim"
                cache_path.parent.mkdir(exist_ok=True)
                cache_path.write_text(json.dumps(nominatim_cache, indent=1))
            if not hit:
                stats["unresolved"] += 1
                self.stderr.write(f"  unresolved: {st['opis_id']} {st['city']}, {st['state']}")
                continue
            stats[source] += 1
            prices = st["prices"]
            out.append({
                "opis_id": st["opis_id"], "name": st["name"], "address": st["address"],
                "city": st["city"], "state": st["state"], "rack_id": st["rack_id"],
                "retail_price": f"{min(prices):.5f}", "max_price": f"{max(prices):.5f}",
                "price_count": len(prices), "latitude": f"{hit[0]:.6f}", "longitude": f"{hit[1]:.6f}",
                "geocode_source": source,
            })

        with open(settings.STATIONS_CSV, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(out)} stations to {settings.STATIONS_CSV}: {dict(stats)}"))

    def _read_prices(self):
        stations = {}
        with open(settings.FUEL_PRICES_CSV, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                sid = int(r["OPIS Truckstop ID"])
                st = stations.setdefault(sid, {
                    "opis_id": sid, "name": r["Truckstop Name"].strip(), "address": r["Address"].strip(),
                    "city": r["City"].strip(), "state": r["State"].strip(),
                    "rack_id": r["Rack ID"].strip(), "prices": [],
                })
                st["prices"].append(float(r["Retail Price"]))
        return stations

    def _nominatim(self, city, state, cache):
        key = f"{city}|{state}".lower()
        if key not in cache:
            time.sleep(1.1)  # Nominatim usage policy: max 1 request/second
            try:
                resp = requests.get(
                    settings.NOMINATIM_URL,
                    params={"city": city, "state": state, "country": "USA", "format": "jsonv2", "limit": 1},
                    headers={"User-Agent": settings.HTTP_USER_AGENT},
                    timeout=settings.HTTP_TIMEOUT_SECONDS,
                )
                resp.raise_for_status()
                res = resp.json()
                cache[key] = [float(res[0]["lat"]), float(res[0]["lon"])] if res else None
            except requests.RequestException as exc:
                self.stderr.write(f"  nominatim error for {city}, {state}: {exc}")
                return None
        return (cache[key][0], cache[key][1], city) if cache[key] else None
