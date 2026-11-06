from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from studio.cli import main
from studio.project import Project, read_json

from .helpers import OfflineStudioTest


class CliOfflineTests(OfflineStudioTest):
    def call(self, *args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--root", str(self.root), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_new_preflight_status_and_unknown_estimate_are_offline(self):
        code, output, error = self.call("new", "demo")
        self.assertEqual(code, 0, error)
        project = Project.open(self.root, "demo")
        code, output, error = self.call("preflight", "demo")
        self.assertEqual(code, 0, error)
        preflight = json.loads(output)
        self.assertFalse(preflight["network_checks_executed"])
        self.assertFalse(preflight["paid_calls_executed"])
        self.assertIn("defined", preflight["ark_key_presence"])
        self.assertNotIn("value", preflight["ark_key_presence"])
        code, output, error = self.call("status", "demo")
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["shots"][0]["shot_id"], "SHOT-001")
        code, output, error = self.call("estimate", "demo", "--shot", "SHOT-001")
        self.assertEqual(code, 0, error)
        self.assertFalse(json.loads(output)["known"])

    def test_dry_run_prints_payload_without_network(self):
        project = self.make_project()
        self.prepare_shot(project, paid_config=False, known_pricing=False)
        code, output, error = self.call("dry-run", "demo", "--shot", "SHOT-001")
        self.assertEqual(code, 0, error)
        result = json.loads(output)
        self.assertFalse(result["network_request_sent"])
        self.assertEqual(result["payload"]["model"], "dreamina-seedance-2-0-mini-260615")
        self.assertTrue(result["frame_validation"]["ok"])

    def test_image_dry_run_does_not_execute_cli(self):
        self.make_project()
        code, output, error = self.call(
            "image-dry-run", "demo", "--model", "gpt-image-2.5-flare",
            "--prompt", "A cinematic ceramic cup on a wooden table", "--output", "images/draft.png",
        )
        self.assertEqual(code, 0, error)
        result = json.loads(output)
        self.assertFalse(result["executed"])
        self.assertEqual(result["command"][1:3], ["--model", "gpt-image-2.5-flare"])
        self.assertFalse(Path(self.root / "projects" / "demo" / "images" / "draft.png").exists())
