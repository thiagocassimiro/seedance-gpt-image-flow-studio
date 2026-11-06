from __future__ import annotations

import copy

from studio.costs import estimate_cost
from studio.project import read_json

from .helpers import OfflineStudioTest, known_price


class CostTests(OfflineStudioTest):
    def setUp(self):
        super().setUp()
        self.shot = {
            "id": "SHOT-001", "model": "dreamina-seedance-2-0-mini-260615",
            "duration": 5, "resolution": "720p", "attempts": 1, "quantity": 1, "image_calls": [],
            "image_costs_reconciled": True,
        }
        self.pricing = read_json(self.root / "config" / "pricing.example.json")

    def enable_video_price(self, value="0.20"):
        known_price(self.pricing["video_models"][self.shot["model"]]["resolutions"]["720p"], "price_per_second", value)

    def test_unknown_price_is_not_zero_or_free(self):
        result = estimate_cost(self.shot, self.pricing)
        self.assertFalse(result["known"])
        self.assertIsNone(result["total_amount"])
        self.assertIsNone(result["video"]["price_per_second"])
        self.assertIn("não informado", result["video"]["issues"][0])

    def test_duration_resolution_model_and_attempts_determine_video_cost(self):
        self.enable_video_price("0.25")
        self.shot["attempts"] = 2
        result = estimate_cost(self.shot, self.pricing)
        self.assertTrue(result["known"])
        self.assertEqual(result["video"]["billable_seconds"], "10")
        self.assertEqual(result["total_amount"], "2.50")
        self.assertEqual(result["currency"], "USD")
        self.assertFalse(result["auto_retry_included"])

    def test_image_calls_are_priced_not_assumed_free(self):
        self.enable_video_price("0.20")
        known_price(self.pricing["image_models"]["gpt-image-2.5-flare"]["qualities"]["low"], "price_per_image", "0.04")
        self.shot["image_calls"] = [{"model": "gpt-image-2.5-flare", "quality": "low", "count": 2}]
        result = estimate_cost(self.shot, self.pricing)
        self.assertTrue(result["known"])
        self.assertEqual(result["images"]["amount"], "0.08")
        self.assertEqual(result["total_amount"], "1.08")

    def test_missing_image_declaration_makes_total_unknown(self):
        self.enable_video_price()
        del self.shot["image_calls"]
        result = estimate_cost(self.shot, self.pricing)
        self.assertTrue(result["video"]["known"])
        self.assertFalse(result["known"])
        self.assertIsNone(result["total_amount"])

    def test_price_without_source_date_or_currency_is_unknown(self):
        entry = self.pricing["video_models"][self.shot["model"]]["resolutions"]["720p"]
        entry["price_per_second"] = 0.2
        result = estimate_cost(self.shot, self.pricing)
        self.assertFalse(result["known"])
        self.assertTrue(any("source_url" in issue for issue in result["video"]["issues"]))
