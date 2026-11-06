from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from studio.costs import record_actual_cost, write_cost_report
from studio.errors import AmbiguousSubmissionError, StudioError, ValidationError
from studio.images import ImageRequest, execute_gpt_image, record_image_approval, save_image_estimate
from studio.qc import run_qc
from studio.seedance import (
    ArkClient,
    _active_tasks,
    _OfficialAssetRedirect,
    _SameHostHTTPSRedirect,
    build_payload,
    download_task,
    recover_task,
    submit_task,
)
from studio.seedance import validate_models_config

from .helpers import OFFICIAL_FIRST, OfflineStudioTest


class AdditionalSafetyTests(OfflineStudioTest):
    def test_string_false_never_enables_payment_or_audio(self):
        project = self.make_project()
        shot = self.prepare_shot(project)
        config = project.models_config()
        config["safety"]["allow_paid_submissions"] = "false"
        with self.assertRaises(ValidationError):
            validate_models_config(config)
        config = project.models_config()
        shot["generate_audio"] = "false"
        with self.assertRaises(ValidationError):
            build_payload(shot, config)

    def test_recovery_task_id_reconciles_ambiguous_submission_and_download_is_idempotent(self):
        project = self.make_project()
        self.approve_ready(project)
        post_client = ArkClient(project.models_config(), transport=lambda *args: (200, {"id": "cgt-persist-2"}))
        from studio import seedance as seedance_module
        real_writer = seedance_module.write_versioned_json
        def fail_after_accept(directory, stem, value):
            if stem == "submission":
                raise OSError("disk full")
            return real_writer(directory, stem, value)
        with patch("studio.seedance.write_versioned_json", side_effect=fail_after_accept):
            with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}):
                with self.assertRaises(AmbiguousSubmissionError):
                    submit_task(project, project.shot("SHOT-001"), post_client, True)
        video_url = OFFICIAL_FIRST.replace("pic1.jpg", "recovered.mp4")
        calls = []

        def get_transport(method, url, headers, body, timeout):
            calls.append(method)
            return 200, {"id": "cgt-persist-2", "status": "succeeded", "content": {"video_url": video_url}}

        client = ArkClient(project.models_config(), transport=get_transport, download_transport=lambda url: b"recovered-video")
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}):
            recover_task(project, "cgt-persist-2", client)
            key = next(iter(project.manifest()["idempotency_keys"]))
            self.assertEqual(project.manifest()["idempotency_keys"][key]["task_id"], "cgt-persist-2")
            first = download_task(project, "cgt-persist-2", client)
            second = download_task(project, "cgt-persist-2", client)
        self.assertFalse(_active_tasks(project.manifest()))
        self.assertTrue(second["already_downloaded"])
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertNotIn("POST", calls)

    def test_redirects_cannot_leave_https_or_allowed_hosts(self):
        class Request:
            full_url = OFFICIAL_FIRST

        with self.assertRaises(Exception):
            _SameHostHTTPSRedirect(OFFICIAL_FIRST).redirect_request(Request(), None, 302, None, {}, "https://example.com/steal")
        with self.assertRaises(Exception):
            _OfficialAssetRedirect(["bytepluses.com"]).redirect_request(Request(), None, 302, None, {}, "http://ark-doc.tos-ap-southeast-1.bytepluses.com/insecure")

    def test_image_approval_and_single_use_ledger_with_fake_subprocess(self):
        project = self.make_project()
        self.prepare_shot(project)
        request = ImageRequest(prompt="A cinematic cup", output="images/new.png", model="gpt-image-2.5-flare")
        estimate_path, estimate = save_image_estimate(project, request)
        self.assertTrue(estimate["known"])
        from studio.project import sha256_file
        record_image_approval(project, request, project.relative(estimate_path), "Usuário de Teste", f"APROVO {sha256_file(estimate_path)}")

        def fake_run(command, **kwargs):
            Path(command[command.index("-f") + 1]).write_bytes(b"offline-image")
            return subprocess.CompletedProcess(command, 0, "ok", "")

        with patch("studio.images.subprocess.run", side_effect=fake_run) as runner:
            output = execute_gpt_image(project, request, approved=True)
            self.assertTrue(output.is_file())
            with self.assertRaises(StudioError):
                execute_gpt_image(project, request, approved=True)
        self.assertEqual(runner.call_count, 1)
        entry = next(iter(project.manifest()["image_idempotency_keys"].values()))
        self.assertEqual(entry["status"], "completed")

    def test_failed_image_subprocess_is_ambiguous_and_not_retried(self):
        project = self.make_project()
        self.prepare_shot(project)
        request = ImageRequest(prompt="A cinematic cup", output="images/failure.png", model="gpt-image-2.5-flare")
        estimate_path, _ = save_image_estimate(project, request)
        from studio.project import sha256_file
        record_image_approval(project, request, project.relative(estimate_path), "Usuário de Teste", f"APROVO {sha256_file(estimate_path)}")
        with patch("studio.images.subprocess.run", return_value=subprocess.CompletedProcess(["fake"], 1, "", "uncertain")) as runner:
            with self.assertRaises(AmbiguousSubmissionError):
                execute_gpt_image(project, request, approved=True)
            with self.assertRaises(StudioError):
                execute_gpt_image(project, request, approved=True)
        self.assertEqual(runner.call_count, 1)
        entry = next(iter(project.manifest()["image_idempotency_keys"].values()))
        self.assertEqual(entry["status"], "ambiguous")

    def test_actual_cost_reconciliation_deduplicates_invoice(self):
        project = self.make_project()
        first = record_actual_cost(project, None, "1.25", "USD", "Fatura oficial de teste", "INVOICE-1")
        second = record_actual_cost(project, None, "1.25", "USD", "Fatura oficial de teste", "INVOICE-1")
        self.assertTrue(second["duplicate_ignored"])
        self.assertEqual(len(project.manifest()["actual_costs"]), 1)
        self.assertEqual(first["entry_id"], second["entry_id"])
        path = write_cost_report(project)
        from studio.project import read_json
        self.assertEqual(read_json(path)["totals"], {"USD": "1.25"})

    def test_qc_marks_aggregate_incomplete_when_a_clip_fails(self):
        project = self.make_project()
        project.update_manifest("qc_fixture", lambda value: value.setdefault("clips", []).append({"path": "clips/original/missing.mp4", "kind": "original"}))
        with patch("studio.qc.inspect_clip", return_value={"status": "check_incomplete", "errors": ["missing"]}):
            _, report = run_qc(project)
        self.assertEqual(report["status"], "incomplete")
