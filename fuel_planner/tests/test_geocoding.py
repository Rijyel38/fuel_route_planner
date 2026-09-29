from unittest import mock

from django.test import SimpleTestCase

from fuel_planner.services import gazetteer, geocoding


class GazetteerTests(SimpleTestCase):
    def test_normalization_variants_match(self):
        self.assertEqual(gazetteer.normalize_city("Saint Johns"), gazetteer.normalize_city("St. Johns"))
        self.assertEqual(gazetteer.normalize_city("Mc Calla"), gazetteer.normalize_city("McCalla"))
        self.assertEqual(gazetteer.normalize_city("Cañon City"), gazetteer.normalize_city("Canon City"))

    def test_strip_census_suffix(self):
        self.assertEqual(gazetteer.strip_lsad("Abbeville city"), "Abbeville")
        self.assertEqual(gazetteer.strip_lsad("McCalla CDP"), "McCalla")

    def test_lookup(self):
        lat, lon, _ = gazetteer.lookup("Dallas", "TX")
        self.assertAlmostEqual(lat, 32.8, delta=0.3)
        self.assertAlmostEqual(lon, -96.8, delta=0.3)
        self.assertIsNotNone(gazetteer.lookup("Pecos", "Texas"))  # "Town of Pecos city" in Census


class ResolveTests(SimpleTestCase):
    def test_coordinates(self):
        loc = geocoding.resolve("40.7128, -74.0060")
        self.assertEqual((loc.lat, loc.lon, loc.source), (40.7128, -74.006, "coordinates"))

    def test_coordinates_outside_usa_rejected(self):
        with self.assertRaises(geocoding.GeocodingError):
            geocoding.resolve("51.5, -0.12")  # London

    @mock.patch("fuel_planner.services.geocoding.nominatim")
    def test_city_state_is_offline(self, nominatim):
        loc = geocoding.resolve("Chicago, IL")
        self.assertEqual(loc.source, "census_gazetteer")
        nominatim.assert_not_called()

    @mock.patch("fuel_planner.services.geocoding.nominatim")
    def test_street_address_goes_to_nominatim(self, nominatim):
        geocoding.resolve("1600 Pennsylvania Ave NW, Washington, DC")
        nominatim.assert_called_once()
