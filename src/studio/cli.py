"""CLI local do estúdio; somente submit pode criar uma tarefa paga."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .approvals import record_approval, record_frame_review, shot_status, validate_submission_gates
from .assemble import assemble_project
from .costs import estimate_cost, record_actual_cost, save_estimate, write_cost_report
from .errors import StudioError
from .frames import validate_shot_frames
from .images import ImageRequest, build_gpt_image_command, execute_gpt_image, reconcile_image, record_image_approval, save_image_estimate
from .preflight import save_preflight
from .project import Project, new_project
from .qc import run_qc
from .security import redact_data, redact_text
from .seedance import (
    ArkClient,
    build_payload,
    download_task,
    dry_run_payload,
    list_task_candidates,
    recover_task,
    submit_task,
)


def _print(value: Any) -> None:
    print(json.dumps(redact_data(value), ensure_ascii=False, indent=2))


def _project(args: argparse.Namespace) -> Project:
    return Project.open(args.root, args.project)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studio", description="AI Video Studio — produção local com gastos bloqueados por padrão")
    parser.add_argument("--root", default=str(Path.cwd()), help="raiz do ai-video-studio (padrão: diretório atual)")
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="criar projeto sem chamadas pagas")
    new.add_argument("project")

    for name, help_text in (("preflight", "verificar ferramentas localmente"), ("status", "mostrar etapas e barreiras"), ("qc", "executar QC técnico local")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("project")

    for name in ("estimate", "dry-run"):
        command = commands.add_parser(name, help="estimar custo" if name == "estimate" else "validar e exibir payload sem rede")
        command.add_argument("project")
        command.add_argument("--shot", required=True)

    submit = commands.add_parser("submit", help="submeter uma geração paga previamente aprovada")
    submit.add_argument("project")
    submit.add_argument("--shot", required=True)
    submit.add_argument("--approved", action="store_true", help="confirma a intenção; não substitui a aprovação registrada")

    for name in ("task", "download"):
        command = commands.add_parser(name, help="consultar tarefa existente" if name == "task" else "baixar tarefa existente")
        command.add_argument("project")
        command.add_argument("--task-id", required=True)
        command.add_argument("--idempotency-key", help="associa explicitamente uma reserva ambígua a esta tarefa")

    tasks = commands.add_parser("tasks", help="listar tarefas para recuperação, sem criar nenhuma")
    tasks.add_argument("project")
    tasks.add_argument("--page-size", type=int, default=20)

    approve = commands.add_parser("approve", help="registrar aprovação humana para uma estimativa exata")
    approve.add_argument("project")
    approve.add_argument("--shot", required=True)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--confirmation", required=True, help="texto APROVO <sha256-da-estimativa>")

    review = commands.add_parser("record-frame-review", help="registrar parecer independente, sem alterar o parecer")
    review.add_argument("project")
    review.add_argument("--shot", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--verdict", choices=("approved", "rejected"), required=True)
    review.add_argument("--report", required=True, help="relatório dentro do projeto")

    assemble = commands.add_parser("assemble", help="montar master e entrega com FFmpeg")
    assemble.add_argument("project")
    assemble.add_argument("--dry-run", action="store_true", help="mostrar comandos sem processar mídia")

    cost_report = commands.add_parser("cost-report", help="gravar relatório de custos registrados")
    cost_report.add_argument("project")

    actual_cost = commands.add_parser("record-cost", help="reconciliar custo real de uma fatura")
    actual_cost.add_argument("project")
    actual_cost.add_argument("--task-id")
    actual_cost.add_argument("--amount", required=True)
    actual_cost.add_argument("--currency", required=True)
    actual_cost.add_argument("--source", required=True)
    actual_cost.add_argument("--reference", required=True, help="identificador único da cobrança/fatura")

    reconcile = commands.add_parser("reconcile-image", help="reconciliar imagem ambígua sem reexecutá-la")
    reconcile.add_argument("project")
    reconcile.add_argument("--key", required=True)
    reconcile.add_argument("--status", choices=("completed", "rejected"), required=True)
    reconcile.add_argument("--approved-by", required=True)
    reconcile.add_argument("--evidence", required=True)
    reconcile.add_argument("--output")
    reconcile.add_argument("--confirm-no-charge", action="store_true")

    for name, help_text in (
        ("image-dry-run", "mostrar comando gpt-image sem executá-lo"),
        ("image-estimate", "estimar uma chamada de imagem sem executá-la"),
        ("image-approve", "registrar aprovação humana para uma imagem exata"),
        ("image-submit", "executar uma imagem previamente aprovada"),
    ):
        image = commands.add_parser(name, help=help_text)
        image.add_argument("project")
        image.add_argument("--model", required=True)
        image.add_argument("--prompt", required=True)
        image.add_argument("--output", required=True)
        image.add_argument("--reference", action="append", default=[])
        image.add_argument("--quality", default="low")
        image.add_argument("--size", default="landscape")
        if name == "image-approve":
            image.add_argument("--estimate", required=True)
            image.add_argument("--approved-by", required=True)
            image.add_argument("--confirmation", required=True)
        if name == "image-submit":
            image.add_argument("--approval")
            image.add_argument("--approved", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "new":
            project = new_project(args.root, args.project)
            _print({"created": True, "project": project.name, "path": str(project.root), "paid_calls": 0})
            return 0

        project = _project(args)
        if args.command == "preflight":
            path, report = save_preflight(project)
            _print({"report": project.relative(path), **report})
        elif args.command == "status":
            _print({
                "project": project.name, "stage": project.manifest().get("stage"),
                "revision": project.manifest().get("revision"),
                "shots": [shot_status(project, shot) for shot in project.list_shots()],
                "tasks": redact_data(project.manifest().get("tasks", {})),
            })
        elif args.command == "estimate":
            path, estimate = save_estimate(project, project.shot(args.shot))
            _print({"estimate_path": project.relative(path), **estimate})
        elif args.command == "dry-run":
            shot = project.shot(args.shot)
            result = dry_run_payload(project, shot)
            try:
                result["frame_validation"] = validate_shot_frames(project, shot)
            except Exception as exc:
                result["frame_validation"] = {"ok": False, "errors": [redact_text(str(exc))]}
            result["estimate_preview"] = estimate_cost(shot, project.pricing_config())
            _print(result)
        elif args.command == "approve":
            path, approval = record_approval(project, project.shot(args.shot), args.approved_by, args.confirmation)
            _print({"approval_path": project.relative(path), **approval})
        elif args.command == "record-frame-review":
            path, review = record_frame_review(project, project.shot(args.shot), args.reviewer, args.verdict, args.report)
            _print({"review_path": project.relative(path), **review})
        elif args.command == "submit":
            shot = project.shot(args.shot)
            payload = build_payload(shot, project.models_config())
            gates = validate_submission_gates(project, shot, payload, args.approved)
            _print({"paid_call_summary": {
                "model": payload["model"], "duration": payload["duration"], "resolution": payload["resolution"],
                "quantity": 1, "estimated_amount": gates["estimated_amount"], "currency": gates["currency"],
                "payload_sha256": gates["payload_sha256"], "note": "Uma única tentativa; sem retry automático."
            }})
            result = submit_task(project, shot, ArkClient(project.models_config()), args.approved)
            _print(result)
        elif args.command == "task":
            _print(recover_task(project, args.task_id, ArkClient(project.models_config()), args.idempotency_key))
        elif args.command == "tasks":
            _print(list_task_candidates(project, ArkClient(project.models_config()), args.page_size))
        elif args.command == "download":
            _print(download_task(project, args.task_id, ArkClient(project.models_config()), args.idempotency_key))
        elif args.command == "qc":
            path, report = run_qc(project)
            _print({"report": project.relative(path), **report})
            if report["status"] == "incomplete":
                return 2
        elif args.command == "assemble":
            _print(assemble_project(project, args.dry_run))
        elif args.command == "cost-report":
            path = write_cost_report(project)
            _print({"cost_report": project.relative(path)})
        elif args.command == "record-cost":
            _print(record_actual_cost(project, args.task_id, args.amount, args.currency, args.source, args.reference))
        elif args.command == "reconcile-image":
            _print(reconcile_image(project, args.key, args.status, args.approved_by, args.evidence, args.output, args.confirm_no_charge))
        elif args.command in {"image-dry-run", "image-estimate", "image-approve", "image-submit"}:
            references = tuple(args.reference)
            request = ImageRequest(
                prompt=args.prompt, output=args.output, model=args.model, references=references,
                quality=args.quality, size=args.size,
            )
            if args.command == "image-estimate":
                path, estimate = save_image_estimate(project, request)
                _print({"estimate_path": project.relative(path), **estimate})
            elif args.command == "image-approve":
                path, approval = record_image_approval(project, request, args.estimate, args.approved_by, args.confirmation)
                _print({"approval_path": project.relative(path), **approval})
            elif args.command == "image-submit":
                output = execute_gpt_image(project, request, args.approval, args.approved)
                _print({"executed": True, "output": project.relative(output), "count": 1})
            else:
                absolute_request = ImageRequest(
                    prompt=args.prompt, output=str(project.resolve(args.output)), model=args.model,
                    references=tuple(str(project.resolve(item)) for item in args.reference),
                    quality=args.quality, size=args.size,
                )
                _print({
                    "executed": False, "network_request_sent": False,
                    "command": build_gpt_image_command(absolute_request), "model": args.model,
                    "quality": args.quality, "count": 1,
                    "note": "Nenhuma imagem foi gerada. Execução real exige aprovação vinculada ao request."
                })
        else:
            parser.error("comando desconhecido")
        return 0
    except (StudioError, OSError, ValueError) as exc:
        print(f"ERROR: {redact_text(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
