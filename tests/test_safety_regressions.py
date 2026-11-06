from __future__ import annotations

import os
from unittest.mock import patch

from studio.approvals import record_frame_review, validate_submission_gates
from studio.assemble import build_assembly_command
from studio.costs import estimate_cost
from studio.errors import AmbiguousSubmissionError, ApprovalError, ValidationError
from studio.security import validate_task_id
from studio.seedance import ArkClient, build_payload, submit_task

from .helpers import OfflineStudioTest


class SafetyRegressionTests(OfflineStudioTest):
    def test_http_500_is_ambiguous_not_a_retryable_rejection(self):
        project = self.make_project()
        self.approve_ready(project)
        calls = []

        def transport(method, url, headers, body, timeout):
            calls.append(method)
            return 500, {"error": "possibly accepted"}

        client = ArkClient(project.models_config(), transport=transport)
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}):
            with self.assertRaises(AmbiguousSubmissionError):
                submit_task(project, project.shot("SHOT-001"), client, True)
            with self.assertRaises(Exception):
                submit_task(project, project.shot("SHOT-001"), client, True)
        self.assertEqual(calls.count("POST"), 1)
        entry = next(iter(project.manifest()["idempotency_keys"].values()))
        self.assertEqual(entry["status"], "ambiguous")

    def test_local_persistence_failure_preserves_recovery_task_id(self):
        project = self.make_project()
        self.approve_ready(project)
        client = ArkClient(project.models_config(), transport=lambda *args: (200, {"id": "cgt-persist-1"}))
        from studio import seedance as seedance_module
        real_writer = seedance_module.write_versioned_json
        def fail_after_accept(directory, stem, value):
            if stem == "submission":
                raise OSError("disk full")
            return real_writer(directory, stem, value)
        with patch("studio.seedance.write_versioned_json", side_effect=fail_after_accept):
            with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}):
                with self.assertRaises(AmbiguousSubmissionError) as caught:
                    submit_task(project, project.shot("SHOT-001"), client, True)
        self.assertIn("cgt-persist-1", str(caught.exception))
        entry = next(iter(project.manifest()["idempotency_keys"].values()))
        self.assertEqual(entry["status"], "ambiguous")
        self.assertEqual(entry["recovery_task_id"], "cgt-persist-1")

    def test_new_review_with_same_content_requires_new_approval(self):
        project = self.make_project()
        self.approve_ready(project)
        shot = project.shot("SHOT-001")
        record_frame_review(project, shot, "Revisor Independente de Teste", "approved", "reviews/frames/independent-report.md")
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}), self.assertRaises(ApprovalError):
            validate_submission_gates(project, shot, build_payload(shot, project.models_config()), True)

    def test_unreconciled_image_history_makes_total_unknown(self):
        shot = {
            "id": "SHOT-001", "model": "dreamina-seedance-2-0-mini-260615", "duration": 5,
            "resolution": "720p", "attempts": 1, "quantity": 1, "image_calls": [],
            "image_costs_reconciled": False,
        }
        pricing = self.make_project().pricing_config()
        from .helpers import known_price
        known_price(pricing["video_models"][shot["model"]]["resolutions"]["720p"], "price_per_second", "0.20")
        result = estimate_cost(shot, pricing)
        self.assertFalse(result["known"])
        self.assertTrue(any("reconciliados" in issue for issue in result["images"]["issues"]))

    def test_task_ids_cannot_create_ads_or_windows_reserved_paths(self):
        for value in ("CON", "abc:ads", "abc.", "../abc", "abc/def"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_task_id(value)
        self.assertEqual(validate_task_id("cgt-safe_123"), "cgt-safe_123")

    def test_silent_clip_receives_generated_silence_not_missing_input_audio(self):
        plan = {
            "clips": [{"path": "silent.mp4", "start": 0, "end": 5, "has_audio": False}],
            "include_audio": True, "upscale_1080": True, "freeze_last_seconds": 0,
        }
        command = build_assembly_command(plan, "master.mkv")
        filters = command[command.index("-filter_complex") + 1]
        self.assertIn("anullsrc=channel_layout=stereo", filters)
        self.assertIn("atrim=duration=5.000", filters)
        self.assertNotIn("[0:a]", filters)

    def test_nonfinite_media_values_are_rejected(self):
        with self.assertRaises(ValidationError):
            build_assembly_command({"clips": [{"path": "a.mp4", "start": float("nan")}]}, "master.mkv")
        with self.assertRaises(ValidationError):
            build_assembly_command({"clips": [{"path": "a.mp4"}], "freeze_last_seconds": float("inf")}, "master.mkv")
