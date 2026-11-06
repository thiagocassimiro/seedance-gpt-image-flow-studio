from __future__ import annotations

import base64
import json

from studio.errors import ValidationError
from studio.security import redact_data, validate_image_data_url
from studio.seedance import build_payload, dry_run_payload

from .helpers import OfflineStudioTest


class DataUrlAssetTests(OfflineStudioTest):
    def test_official_data_url_is_accepted_and_redacted(self):
        project = self.make_project()
        shot = self.prepare_shot(project, paid_config=False, known_pricing=False)
        data_url = "data:image/jpeg;base64," + base64.b64encode(b"local-frame-bytes").decode("ascii")
        shot["frames"]["first_url"] = data_url
        payload = build_payload(shot, project.models_config())
        self.assertEqual(payload["content"][1]["image_url"]["url"], data_url)
        rendered = json.dumps(dry_run_payload(project, shot))
        self.assertNotIn("local-frame-bytes", rendered)
        self.assertIn("<data-url-redacted>", rendered)
        self.assertEqual(redact_data(data_url), "<data-url-redacted>")

    def test_invalid_data_urls_are_rejected(self):
        for value in (
            "data:image/png;base64,not-base64!",
            "data:image/PNG;base64,AA==",
            "data:video/mp4;base64,AA==",
            "data:image/png;base64,",
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_image_data_url(value)

    def test_video_and_audio_cannot_use_data_urls(self):
        project = self.make_project()
        shot = self.prepare_shot(project, paid_config=False, known_pricing=False)
        shot["references"] = [{"type": "video_url", "url": "data:video/mp4;base64,AA==", "role": "reference_video"}]
        with self.assertRaises(ValidationError):
            build_payload(shot, project.models_config())
