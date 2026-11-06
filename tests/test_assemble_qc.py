from __future__ import annotations

from studio.assemble import build_assembly_command, build_delivery_command
from studio.errors import ValidationError
from studio.qc import run_qc

from .helpers import OfflineStudioTest


class AssembleAndQcTests(OfflineStudioTest):
    def test_assembly_has_cuts_concat_freeze_color_and_lanczos(self):
        plan = {
            "clips": [{"path": "original.mp4", "start": 0.2, "end": 4.8, "brightness": 0.01, "saturation": 1.05}],
            "include_audio": True, "freeze_last_seconds": 0.5, "upscale_1080": True, "color": {"hue_adjustment": False},
        }
        command = build_assembly_command(plan, "master.mkv")
        filters = command[command.index("-filter_complex") + 1]
        self.assertIn("trim=start=0.200:end=4.800", filters)
        self.assertIn("concat=n=1:v=1:a=1", filters)
        self.assertIn("tpad=stop_mode=clone:stop_duration=0.500", filters)
        self.assertIn("scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos", filters)
        self.assertIn("pad=1920:1080", filters)
        self.assertIn("eq=brightness=0.0100:saturation=1.0500", filters)
        self.assertIn("ffv1", command)
        self.assertIn("flac", command)
        self.assertIn("bt709", command)
        self.assertIn("-n", command)
        self.assertNotIn("-y", command)

    def test_hue_adjustment_is_rejected(self):
        plan = {"clips": [{"path": "original.mp4"}], "color": {"hue_adjustment": True}}
        with self.assertRaises(ValidationError):
            build_assembly_command(plan, "master.mkv")

    def test_delivery_uses_h264_and_preserves_master(self):
        command = build_delivery_command("lossless-master.mkv", "delivery.mp4")
        self.assertIn("libx264", command)
        self.assertIn("lossless-master.mkv", command)
        self.assertIn("-n", command)

    def test_empty_qc_is_offline_and_does_not_claim_motion_or_audio_review(self):
        project = self.make_project()
        path, report = run_qc(project)
        self.assertEqual(report["status"], "pending_no_clips")
        self.assertFalse(report["motion_reviewed"])
        self.assertFalse(report["audio_reviewed"])
        self.assertFalse(report["network_used"])
        self.assertTrue(path.is_file())
