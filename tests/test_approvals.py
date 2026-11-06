from __future__ import annotations

import os
from unittest.mock import patch

from studio.approvals import record_approval, validate_submission_gates
from studio.costs import save_estimate
from studio.errors import ApprovalError
from studio.project import sha256_file
from studio.seedance import build_payload

from .helpers import OfflineStudioTest


class ApprovalTests(OfflineStudioTest):
    def test_submit_gates_refuse_missing_approval_review_and_unknown_cost(self):
        project = self.make_project()
        shot = self.prepare_shot(project, paid_config=False, known_pricing=False)
        with self.assertRaises(ApprovalError) as caught:
            validate_submission_gates(project, shot, build_payload(shot, project.models_config()), True)
        message = str(caught.exception)
        self.assertIn("allow_paid_submissions=false", message)
        self.assertIn("nenhuma aprovação", message)
        self.assertIn("nenhuma revisão", message)

    def test_wrong_confirmation_does_not_create_approval(self):
        project = self.make_project()
        self.prepare_shot(project)
        from studio.approvals import record_frame_review
        record_frame_review(project, project.shot("SHOT-001"), "Revisor Independente", "approved", "reviews/frames/independent-report.md")
        save_estimate(project, project.shot("SHOT-001"))
        with self.assertRaises(ApprovalError):
            record_approval(project, project.shot("SHOT-001"), "Usuário de Teste", "APROVO")
        self.assertEqual(list((project.root / "approvals").rglob("*.json")), [])

    def test_valid_approval_is_bound_to_exact_payload_estimate_and_review(self):
        project = self.make_project()
        prepared = self.approve_ready(project)
        shot = project.shot("SHOT-001")
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}):
            gates = validate_submission_gates(project, shot, build_payload(shot, project.models_config()), True)
        self.assertEqual(gates["estimated_amount"], "1.00")
        self.assertEqual(gates["currency"], "USD")
        self.assertEqual(gates["payload_sha256"], prepared["approval"]["payload_sha256"])

    def test_any_material_change_invalidates_previous_approval(self):
        project = self.make_project()
        self.approve_ready(project)
        changed = project.update_shot("SHOT-001", "material_change", lambda value: value.update({"prompt": "A completely different shot with a moving train."}))
        with patch.dict(os.environ, {"ARK_API_KEY": "offline-secret"}), self.assertRaises(ApprovalError):
            validate_submission_gates(project, changed, build_payload(changed, project.models_config()), True)

    def test_agent_cannot_approve_on_users_behalf(self):
        project = self.make_project()
        prepared = self.approve_ready(project)
        with self.assertRaises(ApprovalError):
            record_approval(project, project.shot("SHOT-001"), "kimi", f"APROVO {sha256_file(prepared['estimate_path'])}")
