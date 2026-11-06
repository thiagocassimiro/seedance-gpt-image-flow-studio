"""Ponte com a CLI gpt-image existente; não reimplementa a API de imagens."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .costs import estimate_single_image
from .errors import AmbiguousSubmissionError, ApprovalError, DuplicateSubmissionError, ToolMissingError, ValidationError
from .project import (
    Project,
    exclusive_lock,
    read_json,
    sha256_file,
    sha256_json,
    utc_now,
    write_versioned_json,
)
from .security import redact_text

SUPPORTED_IMAGE_MODELS = {"gpt-image-2.5-flare", "gpt-image-2.5-sunburst"}
_AUTOMATED_APPROVERS = {"auto", "automatic", "studio", "system", "kimi", "agent", "agente", "bot", "chatgpt", "deepseek"}


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    output: str
    model: str
    references: tuple[str, ...] = ()
    quality: str = "low"
    size: str = "landscape"
    image_format: str = "png"

    def fingerprint(self) -> str:
        return sha256_json(asdict(self))


def _normalized(project: Project, request: ImageRequest) -> ImageRequest:
    return ImageRequest(
        prompt=request.prompt, output=str(project.resolve(request.output)), model=request.model,
        references=tuple(str(project.resolve(item)) for item in request.references),
        quality=request.quality, size=request.size, image_format=request.image_format,
    )


def resolve_gpt_image() -> str:
    executable = shutil.which("gpt-image")
    if executable:
        return executable
    fallback = Path.home() / ".local" / "bin" / "gpt-image.exe"
    if fallback.is_file():
        return str(fallback)
    raise ToolMissingError("CLI gpt-image não encontrada; nenhuma instalação foi tentada")


def build_gpt_image_command(request: ImageRequest, executable: str = "gpt-image") -> list[str]:
    if request.model not in SUPPORTED_IMAGE_MODELS:
        raise ValidationError("modelo de imagem deve ser explicitamente Flare ou Sunburst; não há fallback")
    if not request.prompt.strip():
        raise ValidationError("prompt de imagem vazio")
    if request.model == "gpt-image-2.5-flare" and request.references:
        raise ValidationError("edições com referências usam Sunburst, nunca troca silenciosa de modelo")
    if request.model == "gpt-image-2.5-sunburst" and not request.references:
        raise ValidationError("Sunburst foi reservado a edições com referências; use Flare para exploração sem referências")
    command = [executable, "--model", request.model, "-p", request.prompt, "-f", request.output]
    for reference in request.references:
        if not Path(reference).is_file():
            raise ValidationError(f"referência ausente: {reference}")
        command.extend(["-i", reference])
    command.extend(["--quality", request.quality, "--size", request.size, "-n", "1", "--format", request.image_format])
    return command


def save_image_estimate(project: Project, request: ImageRequest) -> tuple[Path, dict[str, Any]]:
    resolved = _normalized(project, request)
    build_gpt_image_command(resolved)
    estimate = {
        **estimate_single_image(resolved.model, resolved.quality, project.pricing_config()),
        "request_sha256": resolved.fingerprint(), "created_at": utc_now(),
    }
    path = write_versioned_json(project.root / "estimates" / "images", "image", estimate)
    project.audit("image_cost_estimated", {"path": project.relative(path), "known": estimate["known"], "model": resolved.model})
    return path, estimate


def record_image_approval(
    project: Project, request: ImageRequest, estimate_path: str, approved_by: str, confirmation: str,
) -> tuple[Path, dict[str, Any]]:
    approved_by = approved_by.strip()
    if not approved_by or approved_by.lower() in _AUTOMATED_APPROVERS:
        raise ApprovalError("approved_by deve identificar a pessoa; agentes não aprovam")
    resolved = _normalized(project, request)
    build_gpt_image_command(resolved)
    if Path(resolved.output).exists():
        raise ValidationError("a saída já existe; escolha uma nova versão antes da aprovação")
    fingerprint = resolved.fingerprint()
    if fingerprint in project.manifest().get("image_approvals", {}):
        raise ApprovalError("já existe aprovação para este request exato")
    estimate_file = project.resolve(estimate_path)
    estimate = read_json(estimate_file)
    if not estimate.get("known") or estimate.get("request_sha256") != fingerprint:
        raise ApprovalError("estimativa de imagem desconhecida ou pertencente a outro request")
    estimate_digest = sha256_file(estimate_file)
    expected = f"APROVO {estimate_digest}"
    if confirmation.strip() != expected:
        raise ApprovalError(f"confirmação exigida: {expected}")
    approval = {
        "operation": "image_generation", "status": "approved", "approved_by": approved_by,
        "approved_at": utc_now(), "confirmation": expected, "request_sha256": fingerprint,
        "model": resolved.model, "quality": resolved.quality, "count": 1,
        "estimate_path": project.relative(estimate_file), "estimate_sha256": estimate_digest,
        "estimated_amount": estimate["amount"], "currency": estimate["currency"],
        "images_manifest_sha256": sha256_json(project.manifest().get("images", [])),
        "scope_note": "Uma única chamada; não autoriza repetição nem outro prompt/modelo.",
    }
    path = write_versioned_json(project.root / "approvals" / "images", "approval", approval)
    digest = sha256_file(path)

    def update(manifest: dict[str, Any]) -> None:
        manifest.setdefault("image_approvals", {})[fingerprint] = {
            "path": project.relative(path), "sha256": digest, "request_sha256": fingerprint,
        }

    project.update_manifest("human_image_approval_recorded", update)
    project.audit("human_image_approval_recorded", {
        "approved_by": approved_by, "model": resolved.model, "quality": resolved.quality,
        "amount": estimate["amount"], "currency": estimate["currency"],
    })
    return path, approval


def execute_gpt_image(
    project: Project, request: ImageRequest, approval_path: str | None = None, approved: bool = False,
) -> Path:
    """Executa uma vez com aprovação registrada e ledger; qualquer incerteza bloqueia retry."""
    if approved is not True:
        raise ApprovalError("chamada de imagem recusada: aprovação explícita ausente")
    resolved = _normalized(project, request)
    fingerprint = resolved.fingerprint()
    key = "img1_" + fingerprint
    output = Path(resolved.output)
    if output.exists():
        raise ValidationError("a imagem de saída já existe; escolha uma nova versão")
    manifest = project.manifest()
    approval_entry = manifest.get("image_approvals", {}).get(fingerprint)
    if not approval_entry:
        raise ApprovalError("nenhuma aprovação de imagem registrada para este request")
    if approval_path and project.resolve(approval_path) != project.resolve(approval_entry["path"]):
        raise ApprovalError("a aprovação informada não é a registrada no manifesto")
    approval_file = project.resolve(approval_entry["path"])
    if sha256_file(approval_file) != approval_entry["sha256"]:
        raise ApprovalError("o registro de aprovação de imagem foi alterado")
    approval = read_json(approval_file)
    estimate_file = project.resolve(approval.get("estimate_path", ""))
    expected_confirmation = f"APROVO {sha256_file(estimate_file)}"
    required = {
        "operation": "image_generation", "status": "approved", "request_sha256": fingerprint,
        "model": resolved.model, "quality": resolved.quality, "count": 1,
        "estimate_sha256": sha256_file(estimate_file), "confirmation": expected_confirmation,
        "images_manifest_sha256": sha256_json(manifest.get("images", [])),
    }
    for field, expected in required.items():
        if approval.get(field) != expected:
            raise ApprovalError(f"aprovação de imagem diverge em {field}")
    estimate = read_json(estimate_file)
    if estimate.get("request_sha256") != fingerprint or estimate.get("model") != resolved.model or estimate.get("quality") != resolved.quality:
        raise ApprovalError("a estimativa de imagem pertence a outro request")
    if approval.get("estimated_amount") != estimate.get("amount") or approval.get("currency") != estimate.get("currency"):
        raise ApprovalError("valor ou moeda da aprovação diverge da estimativa")
    if not approval.get("approved_by") or str(approval["approved_by"]).lower() in _AUTOMATED_APPROVERS:
        raise ApprovalError("aprovador humano inválido")
    if approval.get("estimated_amount") is None or not approval.get("currency"):
        raise ApprovalError("estimativa conhecida de imagem obrigatória")
    command = build_gpt_image_command(resolved, resolve_gpt_image())

    with exclusive_lock(project.root / "locks" / "paid-submission.lock"):
        from .seedance import _active_tasks
        current = project.manifest()
        if _active_tasks(current):
            raise DuplicateSubmissionError("há tarefa de vídeo ativa/ambígua; imagem paga não será paralela")
        image_entries = current.get("image_idempotency_keys", {})
        if key in image_entries:
            raise DuplicateSubmissionError("este request de imagem já foi reservado; não execute novamente")
        if any(entry.get("status") in {"submitting", "ambiguous"} for entry in image_entries.values()):
            raise DuplicateSubmissionError("há chamada de imagem ativa ou ambígua")
        if approval.get("images_manifest_sha256") != sha256_json(current.get("images", [])):
            raise ApprovalError("o histórico de imagens mudou após a aprovação")
        reservation = {
            "status": "submitting", "request_sha256": fingerprint, "created_at": utc_now(),
            "approval_path": project.relative(approval_file), "output": project.relative(output),
            "references": [{"path": project.relative(Path(item)), "sha256": sha256_file(item)} for item in resolved.references],
        }

        def reserve(value: dict[str, Any]) -> None:
            value.setdefault("image_idempotency_keys", {})[key] = reservation

        project.update_manifest("paid_image_reserved", reserve)
        project.audit("image_call_started", {"model": resolved.model, "quality": resolved.quality, "request_sha256": fingerprint})
        try:
            result = subprocess.run(
                command, shell=False, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=600, check=False,
            )
            if result.returncode != 0 or not output.is_file():
                message = redact_text((result.stderr or result.stdout)[-4000:])
                raise ValidationError(f"resultado de imagem incerto ({result.returncode}): {message}")
            record = write_versioned_json(project.root / "images", output.stem, {
                "created_at": utc_now(), "model": resolved.model, "quality": resolved.quality, "size": resolved.size,
                "output": project.relative(output), "output_sha256": sha256_file(output),
                "references": [{"path": item, "sha256": sha256_file(item)} for item in resolved.references],
                "request_sha256": fingerprint, "approval": project.relative(approval_file), "count": 1,
            })

            def complete(value: dict[str, Any]) -> None:
                value["image_idempotency_keys"][key].update({"status": "completed", "completed_at": utc_now(), "record": project.relative(record)})
                image_record = read_json(record)
                value.setdefault("images", []).append({**image_record, "record": project.relative(record)})

            project.update_manifest("image_recorded", complete)
            project.audit("image_call_completed", {"record": project.relative(record), "model": resolved.model})
            return output
        except Exception as exc:
            message = redact_text(str(exc))

            def ambiguous(value: dict[str, Any]) -> None:
                value["image_idempotency_keys"][key].update({
                    "status": "ambiguous", "error": message, "updated_at": utc_now(),
                    "output": project.relative(output), "output_exists": output.exists(),
                })

            try:
                project.update_manifest("paid_image_ambiguous", ambiguous)
                project.audit("image_call_ambiguous", {"request_sha256": fingerprint, "output_exists": output.exists()})
            except Exception:
                pass
            raise AmbiguousSubmissionError(
                f"resultado de imagem incerto; não execute novamente. Revise conta/arquivo e a chave {key}. "
                f"Saída esperada: {output}"
            ) from exc


def reconcile_image(
    project: Project, key: str, status: str, approved_by: str, evidence: str,
    output_path: str | None = None, confirm_no_charge: bool = False,
) -> dict[str, Any]:
    """Reconcilia uma operação ambígua por decisão humana, sem reexecutar a CLI."""
    approved_by = approved_by.strip()
    if not approved_by or approved_by.lower() in _AUTOMATED_APPROVERS:
        raise ApprovalError("a reconciliação exige identificação humana")
    if len(evidence.strip()) < 10:
        raise ValidationError("descreva a evidência usada na reconciliação")
    entry = project.manifest().get("image_idempotency_keys", {}).get(key)
    if not entry or entry.get("status") != "ambiguous":
        raise ValidationError("somente uma imagem em estado ambiguous pode ser reconciliada")
    status = status.strip().lower()
    if status not in {"completed", "rejected"}:
        raise ValidationError("status de reconciliação deve ser completed ou rejected")
    if status == "rejected":
        if confirm_no_charge is not True:
            raise ApprovalError("rejeição exige --confirm-no-charge e evidência de ausência de cobrança")

        def reject(value: dict[str, Any]) -> None:
            value["image_idempotency_keys"][key].update({
                "status": "rejected", "reconciled_at": utc_now(), "reconciled_by": approved_by,
                "reconciliation_evidence": evidence.strip(), "no_charge_confirmed": True,
            })

        project.update_manifest("ambiguous_image_rejected", reject)
        project.audit("ambiguous_image_rejected", {"key": key, "approved_by": approved_by, "no_charge_confirmed": True})
        return {"key": key, "status": "rejected", "reexecuted": False}

    if not output_path:
        raise ValidationError("reconciliação completed exige --output")
    output = project.resolve(output_path)
    if output != project.resolve(entry["output"]):
        raise ValidationError("o arquivo informado não é a saída reservada para esta operação")
    if not output.is_file():
        raise ValidationError("arquivo de imagem não encontrado para reconciliação")
    approval = read_json(project.resolve(entry["approval_path"]))
    record_data = {
        "created_at": utc_now(), "model": approval.get("model"), "quality": approval.get("quality"),
        "output": project.relative(output), "output_sha256": sha256_file(output),
        "references": entry.get("references", []), "request_sha256": entry["request_sha256"],
        "approval": entry["approval_path"], "count": 1, "reconciled_by": approved_by,
        "reconciliation_evidence": evidence.strip(),
    }
    record = write_versioned_json(project.root / "images", output.stem + "-reconciled", record_data)

    def complete(value: dict[str, Any]) -> None:
        value["image_idempotency_keys"][key].update({
            "status": "completed", "reconciled_at": utc_now(), "reconciled_by": approved_by,
            "reconciliation_evidence": evidence.strip(), "record": project.relative(record),
            "output_sha256": record_data["output_sha256"],
        })
        value.setdefault("images", []).append({**record_data, "record": project.relative(record)})

    project.update_manifest("ambiguous_image_completed", complete)
    project.audit("ambiguous_image_completed", {"key": key, "approved_by": approved_by, "record": project.relative(record)})
    return {"key": key, "status": "completed", "record": project.relative(record), "reexecuted": False}
