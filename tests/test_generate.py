import html
import unittest

from generator import generate


class GeneratorConfigurationTests(unittest.TestCase):
    def test_location_is_required(self):
        error = generate.validate_location_config("", "", "", "")
        self.assertIn("WEATHER_LAT", error)
        self.assertIn("WEATHER_LABEL", error)

    def test_location_coordinates_are_validated(self):
        self.assertIsNotNone(generate.validate_location_config("91", "0", "x", "x"))
        self.assertIsNotNone(generate.validate_location_config("0", "181", "x", "x"))
        self.assertIsNone(generate.validate_location_config("39.9", "-75.3", "Town", "Area"))

    def test_prompt_uses_configured_area_and_fahrenheit(self):
        old_label = generate.WEATHER_LABEL
        old_place = generate.PLACE
        try:
            generate.WEATHER_LABEL = "Example area"
            generate.PLACE = "Example location"
            weather = {
                "code": 3,
                "temperature_c": 20,
                "temperature_f": 68,
                "wind_kmh": 5,
                "humidity": 50,
                "cloud_cover": 100,
                "precipitation_mm": 0,
                "is_day": True,
                "local_hour": 12,
            }
            prompt = generate.build_prompt(weather, "style", "camera")
            self.assertIn("LOCAL CONDITIONS near Example area", prompt)
            self.assertIn("68°F", prompt)
            self.assertNotIn("20°C", prompt)
        finally:
            generate.WEATHER_LABEL = old_label
            generate.PLACE = old_place

    def test_gallery_prompt_is_escaped_and_weather_is_fahrenheit(self):
        card = generate._gallery_card("image.jpg", {
            "generated_at_local": "2026-01-01 12:00",
            "wildstyle": "W1-example",
            "prompt": "<script>alert('x')</script>",
            "weather": {"label": "clear", "temperature_c": 20,
                        "wind_kmh": 10, "is_day": True},
        })
        self.assertIn("68°F", card)
        self.assertNotIn("20°C", card)
        self.assertIn(html.escape("<script>alert('x')</script>"), card)
        self.assertIn("<details>", card)


if __name__ == "__main__":
    unittest.main()
