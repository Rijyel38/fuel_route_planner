from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from fuel_planner.models import FuelStation
from fuel_planner.services import stations
from fuel_planner.services.routing import Route

# A straight-ish route due west along latitude 35 from lon -90 to lon -104
# (~790 road miles), with stations placed on it.
LINE = [[-90 - i * 0.1, 35.0] for i in range(141)]


def fake_route(*args, **kwargs):
    return Route(coordinates=LINE, distance_miles=790.0, duration_seconds=790 / 60 * 3600, simplified=LINE)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
@mock.patch("fuel_planner.services.routing.get_route", side_effect=fake_route)
class RouteApiTests(TestCase):
    def setUp(self):
        cache.clear()
        stations.reset_index()
        for i, (lon, price) in enumerate([(-90.2, 3.50), (-93.0, 2.90), (-96.0, 3.80), (-99.0, 3.10), (-103.0, 3.60)]):
            FuelStation.objects.create(
                opis_id=i + 1, name=f"STOP {i + 1}", address="I-40", city="Town", state="AR",
                retail_price=Decimal(str(price)), max_price=Decimal(str(price)), latitude=35.0, longitude=lon,
                geocode_source="test",
            )
        # One far off the route: must be ignored.
        FuelStation.objects.create(
            opis_id=99, name="FAR", address="x", city="x", state="AR", retail_price=Decimal("1.00"),
            max_price=Decimal("1.00"), latitude=37.0, longitude=-95.0, geocode_source="test",
        )

    def tearDown(self):
        stations.reset_index()

    def test_plan_returns_stops_cost_and_map(self, route_mock):
        resp = self.client.post(reverse("route-plan"), {"start": "35,-90", "finish": "35,-104"},
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        route_mock.assert_called_once()

        ids = [s["opis_id"] for s in body["fuel_stops"]]
        self.assertNotIn(99, ids)
        self.assertTrue(all(s["gallons"] > 0 for s in body["fuel_stops"]))
        # Starting empty, every mile is paid for.
        self.assertAlmostEqual(body["summary"]["total_gallons"], 79.0, places=1)
        self.assertAlmostEqual(
            body["summary"]["total_fuel_cost"],
            sum(s["cost"] for s in body["fuel_stops"]) + body["summary"]["initial_fuel"]["cost"],
            delta=0.05,
        )
        # Never more than a tank between consecutive fuel-ups.
        miles = [0] + [s["route_mile"] for s in body["fuel_stops"]] + [body["route"]["distance_miles"]]
        self.assertTrue(all(b - a <= 500 + 1 for a, b in zip(miles, miles[1:])))
        self.assertIn("html_url", body["map"])
        self.assertEqual(body["route"]["geometry"]["type"], "LineString")

    def test_second_request_is_served_from_cache(self, route_mock):
        url = reverse("route-plan") + "?start=35,-90&finish=35,-104"
        self.client.get(url)
        body = self.client.get(url).json()
        self.assertTrue(body["meta"]["cached_plan"])
        self.assertEqual(body["meta"]["external_api_calls"], 0)
        route_mock.assert_called_once()

    def test_unreachable_when_detour_too_small_for_gaps(self, route_mock):
        FuelStation.objects.filter(opis_id__in=[2, 3, 4]).delete()
        stations.reset_index()
        resp = self.client.get(reverse("route-plan"), {"start": "35,-90", "finish": "35,-104"})
        self.assertEqual(resp.status_code, 422)

    def test_validation_error(self, route_mock):
        resp = self.client.post(reverse("route-plan"), {"start": "35,-90"}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("finish", resp.json()["error"])

    def test_map_and_geojson_pages(self, route_mock):
        q = {"start": "35,-90", "finish": "35,-104"}
        self.assertContains(self.client.get(reverse("route-map"), q), "leaflet")
        gj = self.client.get(reverse("route-geojson"), q).json()
        self.assertEqual(gj["type"], "FeatureCollection")
        route_mock.assert_called_once()  # map + geojson reused the cached plan
