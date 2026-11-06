from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from studio.approvals import record_frame_review
from studio.errors import ApprovalError, DuplicateSubmissionError, ValidationError
from studio.images import ImageRequest, execute_gpt_image, reconcile_image, record_image_approval, save_image_estimate
from studio.seedance import ArkClient, _active_tasks, download_task, recover_task, submit_task

from .helpers import OFFICIAL_FIRST, OfflineStudioTest


class FinalBlockerTests(OfflineStudioTest):
    def make_ambiguous_image(self, project):
        self.prepare_shot(project)
        request = ImageRequest(prompt="A cinematic cup", output="images/ambiguous.png", model="gpt-image-2.5-flare")
        estimate_path, _ = save_image_estimate(project, request)
        from studio.project import sha256_file
        record_image_approval(project, request, project.relative(estimate_path), "Usuário de Teste", f"APROVO {sha256_file(estimate_path)}")
        with patch("studio.images.subprocess.run", return_value=subprocess.CompletedProcess(["fake"], 1, "", "uncertain")):
            with self.assertRaises(Exception):
                execute_gpt_image(project, request, approved=True)
        return next(iter(project.manifest()["image_idempotency_keys"]))

    def test_signed_urls_are_redacted_in_status_and_review_records_but_kept_in_manifest(self):
        project = self.make_project()
        shot = self.prepare_shot(project)
        signed_frame = OFFICIAL_FIRST + "?X-Tos-Signature=frame-secret"
        shot = project.update_shot("SHOT-001", "signed_review_fixture", lambda value: value["frames"].update({"first_url": signed_frame}))
        review_path, review = record_frame_review(project, shot, "Revisor Independente", "approved", "reviews/frames/independent-report.md")
        self.assertNotIn("frame-secret", review_path.read_text(encoding="utf-8"))
        video_url = OFFICIAL_FIRST.replace("pic1.jpg", "clip.mp4") + "?X-Tos-Signature=video-secret"
        client = ArkClient(project.models_config(), transport=lambda *args: (200, {
            "id": "cgt-signed-1", "status": "succeeded", "content": {"video_url": video_url},
        }))
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}):
            recover_task(project, "cgt-signed-1", client)
        task = project.manifest()["tasks"]["cgt-signed-1"]
        self.assertEqual(task["video_url"], video_url)
        record_path = project.resolve(task["latest_status_record"])
        self.assertNotIn("video-secret", record_path.read_text(encoding="utf-8"))

    def test_task_belonging_to_another_key_cannot_be_reused(self):
        project = self.make_project()
        self.prepare_shot(project)

        def fixture(manifest):
            manifest["idempotency_keys"] = {
                "key-one": {"task_id": "cgt-owned-1", "status": "succeeded", "shot_id": "SHOT-001"},
                "key-two": {"task_id": None, "status": "ambiguous", "shot_id": "SHOT-001"},
            }
            manifest["tasks"]["cgt-owned-1"] = {
                "task_id": "cgt-owned-1", "idempotency_key": "key-one", "status": "succeeded",
                "local_file": "clips/original/already.mp4", "local_sha256": "abc",
            }
        project.update_manifest("association_fixture", fixture)
        calls = []
        client = ArkClient(project.models_config(), transport=lambda *args: calls.append(args) or (200, {}))
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}):
            with self.assertRaises(ValidationError):
                recover_task(project, "cgt-owned-1", client, "key-two")
            with self.assertRaises(ValidationError):
                download_task(project, "cgt-owned-1", client, "key-two")
        self.assertEqual(calls, [])
        self.assertEqual(project.manifest()["idempotency_keys"]["key-two"]["status"], "ambiguous")

    def test_ambiguous_image_blocks_video_post(self):
        project = self.make_project()
        self.make_ambiguous_image(project)
        self.approve_ready(project)
        calls = []
        client = ArkClient(project.models_config(), transport=lambda *args: calls.append(args) or (200, {"id": "cgt-never-1"}))
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}):
            with self.assertRaises(DuplicateSubmissionError):
                submit_task(project, project.shot("SHOT-001"), client, True)
        self.assertEqual(calls, [])

    def test_ambiguous_image_can_be_completed_with_hash_without_reexecution(self):
        project = self.make_project()
        key = self.make_ambiguous_image(project)
        entry = project.manifest()["image_idempotency_keys"][key]
        output = project.resolve(entry["output"])
        output.write_bytes(b"reconciled-image")
        with patch("studio.images.subprocess.run") as runner:
            result = reconcile_image(project, key, "completed", "Usuário de Teste", "Arquivo local e cobrança reconciliados", entry["output"])
        self.assertEqual(result["status"], "completed")
        self.assertFalse(runner.called)
        self.assertFalse(_active_tasks(project.manifest()))
        self.assertEqual(len(project.manifest()["images"]), 1)

    def test_ambiguous_image_rejection_requires_no_charge_evidence(self):
        project = self.make_project()
        key = self.make_ambiguous_image(project)
        with self.assertRaises(ApprovalError):
            reconcile_image(project, key, "rejected", "Usuário de Teste", "Fatura oficial confirma ausência de cobrança")
        result = reconcile_image(
            project, key, "rejected", "Usuário de Teste", "Fatura oficial confirma ausência de cobrança",
            confirm_no_charge=True,
        )
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(_active_tasks(project.manifest()))
