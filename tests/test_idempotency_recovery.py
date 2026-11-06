from __future__ import annotations

import os
from unittest.mock import patch

from studio.errors import AmbiguousSubmissionError, StudioError
from studio.seedance import ArkClient, download_task, recover_task, submit_task

from .helpers import OFFICIAL_FIRST, OfflineStudioTest


class IdempotencyAndRecoveryTests(OfflineStudioTest):
    def test_successful_submission_is_never_duplicated(self):
        project = self.make_project()
        self.approve_ready(project)
        calls = []

        def transport(method, url, headers, body, timeout):
            calls.append(method)
            if method == "POST":
                return 200, {"id": "cgt-offline-123"}
            return 200, {"id": "cgt-offline-123", "status": "running"}

        client = ArkClient(project.models_config(), transport=transport)
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}):
            result = submit_task(project, project.shot("SHOT-001"), client, True)
            self.assertEqual(result["task_id"], "cgt-offline-123")
            with self.assertRaises(StudioError):
                submit_task(project, project.shot("SHOT-001"), client, True)
        self.assertEqual(calls.count("POST"), 1)
        self.assertEqual(len(project.manifest()["idempotency_keys"]), 1)

    def test_timeout_marks_ambiguous_and_forbids_second_post(self):
        project = self.make_project()
        self.approve_ready(project)
        calls = []

        def transport(method, url, headers, body, timeout):
            calls.append(method)
            raise TimeoutError("offline timeout")

        client = ArkClient(project.models_config(), transport=transport)
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}):
            with self.assertRaises(AmbiguousSubmissionError):
                submit_task(project, project.shot("SHOT-001"), client, True)
            with self.assertRaises(StudioError):
                submit_task(project, project.shot("SHOT-001"), client, True)
        self.assertEqual(calls.count("POST"), 1)
        entry = next(iter(project.manifest()["idempotency_keys"].values()))
        self.assertEqual(entry["status"], "ambiguous")

    def test_response_without_task_id_is_also_ambiguous(self):
        project = self.make_project()
        self.approve_ready(project)
        client = ArkClient(project.models_config(), transport=lambda *args: (200, {}))
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}), self.assertRaises(AmbiguousSubmissionError):
            submit_task(project, project.shot("SHOT-001"), client, True)
        entry = next(iter(project.manifest()["idempotency_keys"].values()))
        self.assertEqual(entry["status"], "ambiguous")

    def test_recovery_and_download_use_only_existing_task_and_preserve_url(self):
        project = self.make_project()
        self.prepare_shot(project)
        calls = []
        video_url = OFFICIAL_FIRST.replace("pic1.jpg", "clip.mp4") + "?X-Tos-Signature=signed-secret"

        def transport(method, url, headers, body, timeout):
            calls.append(method)
            self.assertEqual(method, "GET")
            return 200, {"id": "cgt-recover-1", "status": "succeeded", "content": {"video_url": video_url}}

        client = ArkClient(
            project.models_config(), transport=transport,
            download_transport=lambda url: b"\x00\x00\x00\x18ftypisom-offline-video",
        )
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}):
            recovered = recover_task(project, "cgt-recover-1", client)
            self.assertEqual(recovered["status"], "succeeded")
            downloaded = download_task(project, "cgt-recover-1", client)
        self.assertNotIn("POST", calls)
        self.assertEqual(project.manifest()["tasks"]["cgt-recover-1"]["video_url"], video_url)
        self.assertEqual(project.manifest()["tasks"]["cgt-recover-1"]["local_sha256"], downloaded["sha256"])
        self.assertTrue(project.resolve(downloaded["path"]).is_file())
        audit = (project.root / "logs" / "audit.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("signed-secret", audit)
        self.assertNotIn("offline-secret", audit)
