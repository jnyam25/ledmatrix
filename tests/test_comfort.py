import unittest

from app.comfort import comfort

_ICONS = {"clear", "fair", "cloud", "fog", "rain", "snow", "storm"}


class ComfortTests(unittest.TestCase):
    def test_cold_air_uses_the_snow_icon(self):
        self.assertEqual(comfort(32, 40), ("snow", "COLD"))

    def test_mild_dry_air_is_clear(self):
        self.assertEqual(comfort(70, 40), ("clear", "MILD"))

    def test_mild_wet_air_is_damp(self):
        self.assertEqual(comfort(70, 80), ("fog", "DAMP"))

    def test_warm_humid_air_is_muggy(self):
        self.assertEqual(comfort(82, 75), ("rain", "MUGGY"))

    def test_hot_dry_air_is_a_sun(self):
        self.assertEqual(comfort(96, 20), ("clear", "HOT"))

    def test_hot_humid_air_is_steamy(self):
        self.assertEqual(comfort(96, 60), ("storm", "STEAMY"))

    def test_every_reading_maps_to_a_real_icon(self):
        for temp in range(30, 110, 7):
            for humid in range(0, 101, 15):
                kind, label = comfort(temp, humid)
                self.assertIn(kind, _ICONS)
                self.assertTrue(label)
