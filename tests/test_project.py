from __future__ import annotations

from studio.errors import ValidationError
from studio.project import normalize_project_name, read_json

from .helpers import OfflineStudioTest


class ProjectTests(OfflineStudioTest):
    def test_new_project_has_no_approval_or_paid_task(self):
        project = self.make_project()
        manifest = project.manifest()
        self.assertEqual(manifest["tasks"], {})
        self.assertEqual(manifest["idempotency_keys"], {})
        self.assertEqual(list((project.root / "approvals").rglob("*.json")), [])
        self.assertFalse(project.models_config()["safety"]["allow_paid_submissions"])
        self.assertFalse((project.root / ".env").exists())

    def test_project_names_and_windows_paths_are_constrained(self):
        for value in ("../evil", "..\\evil", "C:\\evil", "CON", "a/b"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                normalize_project_name(value)
        self.assertEqual(normalize_project_name("Meu Filme_01"), "meu-filme-01")

    def test_manifest_update_preserves_previous_version(self):
        project = self.make_project()
        original = project.manifest()
        project.update_manifest("offline_test", lambda value: value.update({"stage": "story"}))
        history = list((project.root / "history" / "manifest").glob("*.json"))
        self.assertEqual(len(history), 1)
        self.assertEqual(read_json(history[0]), original)
        self.assertEqual(project.manifest()["revision"], 1)
        self.assertEqual(project.manifest()["stage"], "story")

    def test_shot_update_preserves_previous_version(self):
        project = self.make_project()
        original = project.shot("SHOT-001")
        project.update_shot("SHOT-001", "offline_test", lambda value: value.update({"status": "story_review"}))
        history = list((project.root / "history" / "shots" / "SHOT-001").glob("*.json"))
        self.assertEqual(len(history), 1)
        self.assertEqual(read_json(history[0]), original)

    def test_project_cannot_escape_root_or_be_recreated(self):
        project = self.make_project()
        with self.assertRaises(ValidationError):
            project.resolve("..\\outside.txt")
        with self.assertRaises(ValidationError):
            self.make_project()
