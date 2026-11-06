from __future__ import annotations

from studio.security import redact_data

from .helpers import OfflineStudioTest


class UsageRedactionTests(OfflineStudioTest):
    def test_usage_counts_survive_but_access_tokens_are_redacted(self):
        result = redact_data({
            "usage": {"completion_tokens": 102960, "total_tokens": 102960},
            "access_token": "must-not-leak",
            "nested": {"input_tokens": 10, "output_tokens": 20},
        })
        self.assertEqual(result["usage"]["completion_tokens"], 102960)
        self.assertEqual(result["usage"]["total_tokens"], 102960)
        self.assertEqual(result["nested"]["input_tokens"], 10)
        self.assertEqual(result["nested"]["output_tokens"], 20)
        self.assertEqual(result["access_token"], "<redacted>")
