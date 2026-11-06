from __future__ import annotations

import json
import os
from unittest.mock import patch

from studio.errors import ValidationError
from studio.seedance import build_payload, dry_run_payload

from .helpers import OFFICIAL_FIRST, OFFICIAL_LAST, OfflineStudioTest


class PayloadTests(OfflineStudioTest):
    def test_payload_uses_exact_model_and_first_last_roles(self):
        project = self.make_project()
        shot = self.prepare_shot(project, paid_config=False, known_pricing=False)
        payload = build_payload(shot, project.models_config())
        self.assertEqual(payload["model"], "dreamina-seedance-2-0-mini-260615")
        self.assertEqual(payload["duration"], 5)
        self.assertEqual(payload["resolution"], "720p")
        self.assertEqual(payload["content"][1]["role"], "first_frame")
        self.assertEqual(payload["content"][2]["role"], "last_frame")
        self.assertEqual(payload["content"][0]["text"], shot["prompt"])

    def test_dry_run_never_sends_request_and_redacts_secrets_and_signed_urls(self):
        project = self.make_project()
        shot = self.prepare_shot(project, paid_config=False, known_pricing=False)
        secret = "offline-secret-never-print"
        signed = OFFICIAL_FIRST + "?X-Tos-Signature=private-signature&X-Tos-Credential=private-credential"
        shot = project.update_shot("SHOT-001", "signed_url_fixture", lambda value: value["frames"].update({"first_url": signed}))
        with patch.dict(os.environ, {"ARK_API_KEY": secret}):
            result = dry_run_payload(project, shot)
            rendered = json.dumps(result, ensure_ascii=False)
            self.assertNotIn(secret, rendered)
            self.assertNotIn("private-signature", rendered)
            self.assertNotIn("private-credential", rendered)
        self.assertFalse(result["network_request_sent"])
        self.assertEqual(result["headers"]["Authorization"], "Bearer <redacted>")

    def test_unavailable_or_unknown_model_is_not_switched(self):
        project = self.make_project()
        shot = self.prepare_shot(project, paid_config=False, known_pricing=False)
        shot["model"] = "dreamina-seedance-2-5-260628"
        payload = build_payload(shot, project.models_config())
        self.assertEqual(payload["model"], "dreamina-seedance-2-5-260628")
        shot["model"] = "model-not-configured"
        with self.assertRaisesRegex(ValidationError, "nenhuma troca automática"):
            build_payload(shot, project.models_config())

    def test_nonofficial_asset_and_missing_frames_are_rejected(self):
        project = self.make_project()
        shot = self.prepare_shot(project, paid_config=False, known_pricing=False)
        shot["frames"]["first_url"] = "https://example.com/first.png"
        with self.assertRaisesRegex(ValidationError, "não autorizado"):
            build_payload(shot, project.models_config())
        shot["frames"]["first_url"] = OFFICIAL_FIRST
        shot["frames"]["last_url"] = None
        with self.assertRaisesRegex(ValidationError, "primeiro e último"):
            build_payload(shot, project.models_config())

    def test_chinese_endpoint_from_guide_is_not_reused(self):
        project = self.make_project()
        config = project.models_config()
        config["endpoint_base"] = "https://ark.cn-beijing.volces.com"
        with self.assertRaises(ValidationError):
            build_payload(self.prepare_shot(project), config)
