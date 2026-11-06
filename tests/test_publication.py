from __future__ import annotations

import os
from unittest.mock import patch

from scripts.check_publication import scan

from .helpers import OfflineStudioTest


class PublicationSafetyTests(OfflineStudioTest):
    def test_safe_publication_tree_passes(self):
        publish = self.root / "publish"
        publish.mkdir()
        (publish / "README.md").write_text("Projeto sem credenciais\n", encoding="utf-8")
        checked, issues = scan(publish)
        self.assertEqual(checked, 1)
        self.assertEqual(issues, [])

    def test_environment_secret_is_reported_without_printing_value(self):
        publish = self.root / "publish"
        publish.mkdir()
        secret = "offline-secret-never-print-123"
        (publish / "leak.md").write_text(f"valor fictício: {secret}\n", encoding="utf-8")
        with patch.dict(os.environ, {"ARK_API_KEY": secret}):
            _, issues = scan(publish)
        self.assertTrue(any("credencial" in reason for _, reason in issues))
        self.assertNotIn(secret, str(issues))

    def test_private_key_marker_is_blocked(self):
        publish = self.root / "publish"
        publish.mkdir()
        marker = "-----BEGIN " + "PRIVATE KEY-----"
        (publish / "dummy.txt").write_text(marker + "\nconteúdo fictício\n", encoding="utf-8")
        _, issues = scan(publish)
        self.assertTrue(any("chave privada" in reason for _, reason in issues))
