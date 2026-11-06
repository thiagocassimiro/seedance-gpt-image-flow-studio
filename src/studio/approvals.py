"""Revisões independentes e aprovações humanas vinculadas ao payload exato."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .costs import latest_estimate
from .errors import ApprovalError, ValidationError
from .frames import validate_shot_frames
from .project import Project, read_json, sha256_file, sha256_json, utc_now, write_versioned_json
from .seedance import build_payload, idempotency_key, model_definition
from .security import redact_data

_AUTOMATED_NAMES = {"auto", "automatic", "studio", "system", "kimi", "agent", "agente"}


def frame_review_context(project: Project, shot: dict[str, Any]) -> dict[str, Any]:
    frames = shot.get("frames", {})
    first_file = frames.get("first_file")
    last_file = frames.get("last_file")
    if not first_file or not last_file:
        raise ValidationError("revisão independente exige first_file e last_file locais")
    first = project.resolve(first_file)
    last = project.resolve(last_file)
    if not first.is_file() or not last.is_file():
        raise ValidationError("frames locais ausentes para revisão")
    storyboard = project.root / "storyboard.csv"
    palette = project.root / "style" / "palette.json"
    if not storyboard.is_file() or not palette.is_file():
        raise ValidationError("decupagem ou paleta ausente")
    if not str(shot.get("prompt") or "").strip():
        raise ValidationError("prompt vazio antes da revisão de frames")
    dimensions = validate_shot_frames(project, shot)
    return {
        "shot_id": shot["id"],
        "prompt_sha256": sha256_json(shot["prompt"]),
        "frames": {
            "first": {"path": project.relative(first), "sha256": sha256_file(first)},
            "last": {"path": project.relative(last), "sha256": sha256_file(last)},
            "first_url": frames.get("first_url"),
            "last_url": frames.get("last_url"),
            "dimensions_ok": dimensions.get("ok", False),
            "dimension_errors": dimensions.get("errors", []),
        },
        "references_sha256": sha256_json(shot.get("references", [])),
        "storyboard": {"path": "storyboard.csv", "sha256": sha256_file(storyboard)},
        "palette": {"path": "style/palette.json", "sha256": sha256_file(palette)},
        "model": shot.get("model"),
        "duration": shot.get("duration"),
        "resolution": shot.get("resolution"),
        "ratio": shot.get("ratio"),
    }


def record_frame_review(
    project: Project,
    shot: dict[str, Any],
    reviewer: str,
    verdict: str,
    report_path: str,
) -> tuple[Path, dict[str, Any]]:
    reviewer = reviewer.strip()
    verdict = verdict.strip().lower()
    if not reviewer or reviewer.lower() in _AUTOMATED_NAMES:
        raise ValidationError("identifique o revisor independente; não use nome automático")
    if verdict not in {"approved", "rejected"}:
        raise ValidationError("verdict deve ser approved ou rejected")
    report = project.resolve(report_path)
    if not report.is_file():
        raise ValidationError("relatório do revisor não encontrado")
    report_text = report.read_text(encoding="utf-8").strip()
    expected_token = "APROVADO" if verdict == "approved" else "REPROVADO"
    if len(report_text) < 20 or not re.search(rf"\b{expected_token}\b", report_text):
        raise ValidationError(f"relatório precisa conter conteúdo e o veredito explícito {expected_token}")
    context = frame_review_context(project, shot)
    if verdict == "approved" and not context["frames"]["dimensions_ok"]:
        raise ApprovalError("frames com dimensões/proporção inválidas não podem ser aprovados")
    review = {
        "schema_version": 1,
        "operation": "frame_review",
        "shot_id": shot["id"],
        "reviewer": reviewer,
        "reviewer_kind": "independent",
        "verdict": verdict,
        "created_at": utc_now(),
        "report_path": project.relative(report),
        "report_sha256": sha256_file(report),
        "context": redact_data(context),
        "context_sha256": sha256_json(context),
        "files_modified_by_reviewer": False,
    }
    path = write_versioned_json(project.root / "reviews" / "frames" / str(shot["id"]), "review", review)
    digest = sha256_file(path)

    def update(manifest: dict[str, Any]) -> None:
        manifest["shots"].setdefault(str(shot["id"]), {})["latest_frame_review"] = {
            "path": project.relative(path), "sha256": digest, "verdict": verdict,
            "context_sha256": review["context_sha256"],
        }

    project.update_manifest("independent_frame_review_recorded", update)
    project.audit("frame_review_recorded", {"shot_id": shot["id"], "verdict": verdict, "reviewer": reviewer})
    return path, review


def _latest_valid_frame_review(project: Project, shot: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    entry = project.manifest().get("shots", {}).get(str(shot["id"]), {}).get("latest_frame_review")
    if not entry:
        raise ApprovalError("nenhuma revisão independente de frames registrada")
    path = project.resolve(entry["path"])
    if sha256_file(path) != entry["sha256"]:
        raise ApprovalError("a revisão de frames foi alterada")
    review = read_json(path)
    current_context = frame_review_context(project, shot)
    current_digest = sha256_json(current_context)
    if review.get("context_sha256") != current_digest or entry.get("context_sha256") != current_digest:
        raise ApprovalError("prompt, frames, referências, decupagem ou paleta mudaram após a revisão")
    report = project.resolve(review["report_path"])
    if sha256_file(report) != review["report_sha256"]:
        raise ApprovalError("o relatório do revisor foi alterado")
    if review.get("verdict") != "approved" or review.get("reviewer_kind") != "independent":
        raise ApprovalError("a revisão independente de frames não está aprovada")
    if not current_context["frames"]["dimensions_ok"]:
        raise ApprovalError("a validação local das dimensões dos frames falhou")
    return path, review


def record_approval(
    project: Project,
    shot: dict[str, Any],
    approved_by: str,
    confirmation: str,
) -> tuple[Path, dict[str, Any]]:
    approved_by = approved_by.strip()
    if not approved_by or approved_by.lower() in _AUTOMATED_NAMES:
        raise ApprovalError("approved_by deve identificar a pessoa que aprovou; agentes não podem aprovar")
    estimate_path, estimate = latest_estimate(project, str(shot["id"]))
    estimate_digest = sha256_file(estimate_path)
    expected_confirmation = f"APROVO {estimate_digest}"
    if confirmation.strip() != expected_confirmation:
        raise ApprovalError(f"confirmação exigida: {expected_confirmation}")
    if not estimate.get("known") or estimate.get("total_amount") is None or not estimate.get("currency"):
        raise ApprovalError("a estimativa total precisa ser conhecida, com valor e moeda")
    if estimate.get("shot_sha256") != sha256_json(shot):
        raise ApprovalError("o shot mudou depois da estimativa; estime novamente")
    if shot.get("attempts", 1) != 1 or shot.get("quantity", 1) != 1:
        raise ApprovalError("cada aprovação cobre exatamente uma geração; crie outra versão para nova tentativa")
    review_path, review = _latest_valid_frame_review(project, shot)
    payload = build_payload(shot, project.models_config())
    approval = {
        "schema_version": 1,
        "operation": "video_generation",
        "status": "approved",
        "shot_id": shot["id"],
        "approved_by": approved_by,
        "approved_at": utc_now(),
        "confirmation": confirmation.strip(),
        "model": payload["model"],
        "duration_seconds": payload["duration"],
        "resolution": payload["resolution"],
        "quantity": 1,
        "attempts": 1,
        "estimate_path": project.relative(estimate_path),
        "estimate_sha256": estimate_digest,
        "estimated_amount": estimate["total_amount"],
        "currency": estimate["currency"],
        "shot_sha256": sha256_json(shot),
        "payload_sha256": sha256_json(payload),
        "frame_review_path": project.relative(review_path),
        "frame_review_sha256": review["context_sha256"],
        "frame_review_record_sha256": sha256_file(review_path),
        "scope_note": "Aprova uma única submissão do payload exato; não autoriza retries, upgrades nem outras chamadas.",
    }
    path = write_versioned_json(project.root / "approvals" / str(shot["id"]), "approval", approval)
    digest = sha256_file(path)

    def update(manifest: dict[str, Any]) -> None:
        manifest["shots"].setdefault(str(shot["id"]), {})["latest_approval"] = {
            "path": project.relative(path), "sha256": digest,
            "payload_sha256": approval["payload_sha256"], "estimate_sha256": estimate_digest,
        }

    project.update_manifest("human_approval_recorded", update)
    project.audit("human_approval_recorded", {
        "shot_id": shot["id"], "approved_by": approved_by, "model": payload["model"],
        "duration": payload["duration"], "resolution": payload["resolution"],
        "amount": estimate["total_amount"], "currency": estimate["currency"],
    })
    return path, approval


def validate_submission_gates(
    project: Project,
    shot: dict[str, Any],
    payload: dict[str, Any],
    approved_flag: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    if not approved_flag:
        errors.append("flag --approved ausente")
    config = project.models_config()
    if config.get("safety", {}).get("allow_paid_submissions", False) is not True:
        errors.append("allow_paid_submissions=false na configuração")
    definition = model_definition(config, str(shot.get("model")))
    if definition.get("enabled_for_submission", False) is not True:
        errors.append("modelo não habilitado para submissão")
    if definition.get("availability") != "verified_available":
        errors.append("disponibilidade do modelo não foi verificada na conta")
    if not os.environ.get("ARK_API_KEY"):
        errors.append("ARK_API_KEY ausente no processo")
    if shot.get("attempts", 1) != 1 or shot.get("quantity", 1) != 1:
        errors.append("somente uma geração por aprovação/submissão")

    estimate_path = None
    estimate = None
    try:
        estimate_path, estimate = latest_estimate(project, str(shot["id"]))
        if not estimate.get("known") or estimate.get("total_amount") is None or not estimate.get("currency"):
            errors.append("estimativa conhecida obrigatória")
        if estimate.get("shot_sha256") != sha256_json(shot):
            errors.append("shot mudou após a estimativa")
        if estimate.get("video", {}).get("model") != payload.get("model"):
            errors.append("modelo da estimativa diverge do payload")
    except (ValidationError, ApprovalError) as exc:
        errors.append(str(exc))

    review_path = None
    review = None
    try:
        review_path, review = _latest_valid_frame_review(project, shot)
    except (ValidationError, ApprovalError) as exc:
        errors.append(str(exc))

    approval_path = None
    approval = None
    approval_entry = project.manifest().get("shots", {}).get(str(shot["id"]), {}).get("latest_approval")
    if not approval_entry:
        errors.append("nenhuma aprovação humana registrada")
    else:
        approval_path = project.resolve(approval_entry["path"])
        try:
            if sha256_file(approval_path) != approval_entry["sha256"]:
                raise ApprovalError("o registro de aprovação foi alterado")
            approval = read_json(approval_path)
            expected = {
                "operation": "video_generation", "status": "approved", "shot_id": shot["id"],
                "model": payload["model"], "duration_seconds": payload["duration"],
                "resolution": payload["resolution"], "quantity": 1,
                "payload_sha256": sha256_json(payload), "shot_sha256": sha256_json(shot),
            }
            for field, value in expected.items():
                if approval.get(field) != value:
                    errors.append(f"aprovação não corresponde ao campo {field}")
            if estimate_path and approval.get("estimate_sha256") != sha256_file(estimate_path):
                errors.append("aprovação pertence a outra estimativa")
            if review and approval.get("frame_review_sha256") != review["context_sha256"]:
                errors.append("aprovação pertence a outro contexto de revisão de frames")
            if review_path and approval.get("frame_review_path") != project.relative(review_path):
                errors.append("aprovação pertence a outro arquivo de revisão de frames")
            if review_path and approval.get("frame_review_record_sha256") != sha256_file(review_path):
                errors.append("uma nova revisão de frames exige nova aprovação")
            if not approval.get("approved_by") or str(approval["approved_by"]).lower() in _AUTOMATED_NAMES:
                errors.append("aprovador humano inválido")
        except (OSError, ValueError, ApprovalError) as exc:
            errors.append(str(exc))

    key = idempotency_key(project.manifest()["project_id"], str(shot["id"]), payload)
    if key in project.manifest().get("idempotency_keys", {}):
        errors.append("idempotency key já registrada; recuperação é obrigatória, novo POST proibido")
    if errors:
        raise ApprovalError("; ".join(errors))
    return {
        "estimate_path": project.relative(estimate_path),
        "approval_path": project.relative(approval_path),
        "frame_review_path": project.relative(review_path),
        "payload_sha256": sha256_json(payload),
        "idempotency_key": key,
        "estimated_amount": estimate["total_amount"],
        "currency": estimate["currency"],
    }


def shot_status(project: Project, shot: dict[str, Any]) -> dict[str, Any]:
    entry = project.manifest().get("shots", {}).get(str(shot["id"]), {})
    try:
        frames = validate_shot_frames(project, shot)
    except (ValidationError, OSError) as exc:
        frames = {"ok": False, "checked": False, "errors": [str(exc)]}
    return {
        "shot_id": shot["id"], "stage": shot.get("status"), "model": shot.get("model"),
        "duration": shot.get("duration"), "resolution": shot.get("resolution"),
        "frames": frames, "latest_estimate": entry.get("latest_estimate"),
        "latest_frame_review": entry.get("latest_frame_review"), "latest_approval": entry.get("latest_approval"),
        "paid_submission_allowed_by_config": project.models_config().get("safety", {}).get("allow_paid_submissions", False),
    }
