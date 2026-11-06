from __future__ import annotations

from pathlib import Path

from studio.errors import ValidationError
from studio.frames import (
    build_contact_sheet_command,
    build_extract_frame_command,
    build_grayscale_command,
    build_overlay_command,
    compare_frame_dimensions,
)
from studio.images import ImageRequest, build_gpt_image_command

from .helpers import OfflineStudioTest, make_png


class FrameAndImageTests(OfflineStudioTest):
    def test_frame_dimensions_and_ratio(self):
        first = make_png(self.root / "first.png", 1280, 720)
        last = make_png(self.root / "last.png", 1280, 720)
        result = compare_frame_dimensions(first, last, "16:9")
        self.assertTrue(result["ok"])
        self.assertEqual(result["first"]["width"], 1280)

    def test_mismatched_dimensions_and_ratio_fail_before_video(self):
        first = make_png(self.root / "first.png", 1280, 720)
        last = make_png(self.root / "last.png", 1270, 720)
        result = compare_frame_dimensions(first, last, "16:9")
        self.assertFalse(result["ok"])
        self.assertTrue(any("divergentes" in error for error in result["errors"]))
        square = make_png(self.root / "square.png", 720, 720)
        self.assertFalse(compare_frame_dimensions(square, square, "16:9")["ok"])

    def test_ffmpeg_frame_commands_never_overwrite(self):
        commands = [
            build_contact_sheet_command("a.png", "b.png", "contact.png"),
            build_overlay_command("a.png", "b.png", "overlay.png"),
            build_grayscale_command("a.png", "gray.png"),
            build_extract_frame_command("movie.mp4", 1.25, "frame.png"),
        ]
        for command in commands:
            self.assertIn("-n", command)
            self.assertNotIn("-y", command)
        self.assertIn("hstack=inputs=2", commands[0][commands[0].index("-filter_complex") + 1])
        self.assertIn("blend=", commands[1][commands[1].index("-filter_complex") + 1])
        self.assertIn("hue=s=0", commands[2])

    def test_gpt_image_command_is_explicit_one_image_low_draft(self):
        request = ImageRequest(prompt="A cinematic cup on a table", output="draft.png", model="gpt-image-2.5-flare")
        command = build_gpt_image_command(request)
        self.assertEqual(command[command.index("--model") + 1], "gpt-image-2.5-flare")
        self.assertEqual(command[command.index("--quality") + 1], "low")
        self.assertEqual(command[command.index("-n") + 1], "1")
        with self.assertRaises(ValidationError):
            build_gpt_image_command(ImageRequest(prompt="edit", output="edit.png", model="gpt-image-2.5-flare", references=("missing.png",)))
        with self.assertRaises(ValidationError):
            build_gpt_image_command(ImageRequest(prompt="draft", output="draft2.png", model="gpt-image-2.5-sunburst"))
