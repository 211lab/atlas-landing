import html
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from generator import generate


class GeneratorConfigurationTests(unittest.TestCase):
    def test_image_model_selection_uses_random_candidate(self):
        selected = generate.IMAGE_MODELS[2]
        with patch.dict(os.environ, {}, clear=True), patch.object(
                generate.random, "choice", return_value=selected) as choose:
            self.assertEqual(generate.select_image_model(), selected)
            choose.assert_called_once_with(generate.IMAGE_MODELS)

    def test_image_model_override_skips_random_selection(self):
        with patch.dict(os.environ, {"IMAGE_MODEL": "custom/image"}), patch.object(
                generate.random, "choice") as choose:
            self.assertEqual(generate.select_image_model(), "custom/image")
            choose.assert_not_called()

    def test_selected_image_model_and_configured_vision_model_are_used(self):
        image_model = generate.IMAGE_MODELS[0]
        requests = []

        def request(_url, payload, **_kwargs):
            requests.append(payload)
            if "prompt" in payload:
                return {"data": [{"b64_json": "aW1hZ2U="}]}
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        with patch.object(generate, "http_json", side_effect=request), patch.object(
                generate, "refine_image", return_value=b"image"):
            generate.generate_image("prompt", image_model)
            generate.verify_image(b"image", {"code": 0, "is_day": True,
                                               "temperature_f": 70, "local_hour": 12})

        self.assertEqual(requests[0]["model"], image_model)
        self.assertEqual(requests[1]["model"], generate.VISION_MODEL)

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
            recipe = generate.select_recipe()
            prompt = generate.build_prompt(weather, recipe)
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

    def test_gallery_card_shows_escaped_model_ids_and_omits_legacy_fields(self):
        card = generate._gallery_card("image.jpg", {
            "image_model": "image/<model>",
            "vision_model": 'vision/"model',
        })
        self.assertIn("image model: image/&lt;model&gt;", card)
        self.assertIn("vision model: vision/&quot;model", card)

        legacy_card = generate._gallery_card("legacy.jpg", {})
        self.assertNotIn("image model:", legacy_card)
        self.assertNotIn("vision model:", legacy_card)

    def test_gallery_card_escapes_untrusted_image_filename_attributes(self):
        card = generate._gallery_card('bad" onerror="alert(1).jpg', {})
        self.assertIn('href="bad&quot; onerror=&quot;alert(1).jpg"', card)
        self.assertNotIn('href="bad" onerror=', card)
        self.assertNotIn('src="thumbs/bad" onerror=', card)

    def test_gallery_groups_orders_and_marks_up_cards(self):
        with tempfile.TemporaryDirectory() as gallery:
            entries = {
                "20260103-z-new.jpg": {"generated_at_local": "2026-01-03 09:00"},
                "20260103-old.jpg": {"generated_at_local": "2026-01-03 08:00"},
                "20260102-local.jpg": {
                    "generated_at_local": "2026-01-02 23:30",
                    "generated_at": "2026-01-03T04:30:00+00:00",
                },
                "20260101-utc.jpg": {"generated_at": "2026-01-01T23:59:00+00:00"},
                "20251231-unknown.jpg": {},
            }
            for name, metadata in entries.items():
                open(os.path.join(gallery, name), "wb").close()
                with open(os.path.join(gallery, name[:-4] + ".json"), "w") as sidecar:
                    json.dump(metadata, sidecar)

            with patch.object(generate, "GALLERY_DIR", gallery):
                generate._render_gallery_index()

            with open(os.path.join(gallery, "index.html")) as index:
                page = index.read()
            self.assertLess(page.index("<h2>2026-01-03"), page.index("<h2>2026-01-02"))
            self.assertLess(page.index("<h2>2026-01-02"), page.index("<h2>2026-01-01"))
            self.assertLess(page.index("<h2>2026-01-01"), page.index("<h2>Unknown date"))
            self.assertLess(page.index("20260103-z-new.jpg"), page.index("20260103-old.jpg"))
            self.assertLess(page.index("20260102-local.jpg"), page.index("20260101-utc.jpg"))
            self.assertIn('<img loading="lazy" src="thumbs/20260103-z-new.jpg"', page)
            self.assertIn('target="_blank" rel="noopener noreferrer"', page)
            self.assertTrue(os.path.exists(os.path.join(gallery, "catalog.html")))

    def test_recipe_selection_and_prompt_are_complete(self):
        selected = []
        def choose(options):
            selected.append(options)
            return options[0]
        with patch.object(generate.random, "choice", side_effect=choose):
            recipe = generate.select_recipe()
        self.assertEqual(len(selected), len(generate.CATALOGS))
        self.assertEqual(set(recipe), {facet.id for facet in generate.CATALOGS})
        prompt = generate.build_prompt({"code": 0, "is_day": True, "local_hour": 12}, recipe)
        for facet in generate.CATALOGS:
            self.assertIn(recipe[facet.id].description, prompt)
        self.assertIn("exactly uppercase ATLAS", prompt)
        self.assertIn("no other words", prompt)

    def test_catalog_chips_escape_and_legacy_metadata_renders(self):
        info = {"facets": generate.recipe_metadata({f.id: f.entries[0] for f in generate.CATALOGS}),
                "wildstyle": '<script>'}
        card = generate._gallery_card("image.jpg", info)
        self.assertIn("catalog.html#style-wildstyle", card)
        self.assertIn("catalog.html#palette-rainbow", card)
        self.assertNotIn("<script>", card)
        self.assertIn("legacy", generate._gallery_card("legacy.jpg", {"wildstyle": "W1-legacy"}))

    def test_catalog_descriptions_are_detailed_and_rendered_with_chip_targets(self):
        for facet in generate.CATALOGS:
            for entry in facet.entries:
                self.assertGreaterEqual(len(entry.description), 300,
                                        f"{facet.id}/{entry.id} description is too short")
        with tempfile.TemporaryDirectory() as gallery:
            with patch.object(generate, "GALLERY_DIR", gallery):
                generate._render_catalog_index()
            with open(os.path.join(gallery, "catalog.html")) as catalog:
                page = catalog.read()
            recipe = {facet.id: facet.entries[0] for facet in generate.CATALOGS}
            card = generate._gallery_card("image.jpg", {"facets": generate.recipe_metadata(recipe)})
            for facet in generate.CATALOGS:
                entry = recipe[facet.id]
                target = f'{facet.id}-{entry.id}'
                self.assertIn(f'id="{target}"', page)
                self.assertIn(html.escape(entry.description), page)
                self.assertIn(f'href="catalog.html#{target}"', card)


if __name__ == "__main__":
    unittest.main()
