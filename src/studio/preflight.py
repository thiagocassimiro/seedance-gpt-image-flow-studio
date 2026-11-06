"""Preflight exclusivamente local: nenhuma chamada de rede ou instalação."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .project import Project, write_versioned_json
from .seedance import model_definition, validate_models_config


def _probe(name: str, args: list[str], fallback: Path | None = None) -> dict[str, Any]:
    executable = shutil.which(name)
    source = "PATH"
    if not executable and fallback and fallback.is_file():
        executable = str(fallback)
        source = "fallback"
    if not executable:
        return {"name": name, "found": False, "usable": False, "path": None, "error": "não encontrado"}
    try:
        result = subprocess.run(
            [executable, *args], shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15, check=False,
        )
        output = (result.stdout or result.stderr).strip().splitlines()
        return {
            "name": name, "found": True, "usable": result.returncode == 0,
            "path": executable, "source": source, "exit_code": result.returncode,
            "version_or_usage": output[0][:500] if output else None,
            "error": None if result.returncode == 0 else "comando encontrado, mas não executável",
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"name": name, "found": True, "usable": False, "path": executable, "source": source, "error": str(exc)}


def run_preflight(project: Project) -> dict[str, Any]:
    config = project.models_config()
    config_errors: list[str] = []
    try:
        validate_models_config(config)
    except Exception as exc:
        config_errors.append(str(exc))
    current_python = {
        "found": True, "usable": True, "path": sys.executable,
        "version": platform.python_version(), "implementation": platform.python_implementation(),
    }
    tools = {
        "python_runtime": current_python,
        "python_on_path": _probe("python", ["--version"]),
        "ffmpeg": _probe("ffmpeg", ["-version"]),
        "ffprobe": _probe("ffprobe", ["-version"]),
        "gpt_image": _probe("gpt-image", ["--help"], Path.home() / ".local" / "bin" / "gpt-image.exe"),
    }
    models = []
    for model_id in config.get("models", {}):
        try:
            definition = model_definition(config, model_id)
            models.append({
                "id": model_id, "tier": definition.get("tier"),
                "preferred_for_pilot": definition.get("preferred_for_pilot", False),
                "availability": definition.get("availability"),
                "enabled_for_submission": definition.get("enabled_for_submission", False),
            })
        except Exception as exc:
            models.append({"id": model_id, "error": str(exc)})
    key_defined = bool(os.environ.get("ARK_API_KEY"))
    paid_enabled = config.get("safety", {}).get("allow_paid_submissions", False) is True
    report = {
        "schema_version": 1,
        "project": project.name,
        "scope": "local_only",
        "network_checks_executed": False,
        "paid_calls_executed": False,
        "account_model_discovery": config.get("account_discovery", {"status": "not_run"}),
        "tools": tools,
        "ark_key_presence": {"defined": key_defined, "note": "Somente presença verificada; valor não incluído no relatório."},
        "configuration": {"valid": not config_errors, "errors": config_errors, "models": models},
        "ready": {
            "offline_payload_dry_run": not config_errors,
            "frame_and_postproduction": tools["ffmpeg"]["usable"] and tools["ffprobe"]["usable"],
            "image_cli": tools["gpt_image"]["usable"],
            "paid_submission": False,
        },
        "paid_submission_blockers": [
            *([] if key_defined else ["ARK_API_KEY ausente no processo"]),
            *([] if paid_enabled else ["allow_paid_submissions=false"]),
            "Disponibilidade dos modelos e preços exigem confirmação antes de qualquer pagamento.",
        ],
        "installation_actions_taken": [],
        "notes": [
            "Python do runtime é suficiente para os testes; um alias quebrado no PATH não invalida esse runtime.",
            "FFmpeg/ffprobe ausentes são relatados, nunca instalados automaticamente.",
        ],
    }
    return report


def save_preflight(project: Project) -> tuple[Path, dict[str, Any]]:
    report = run_preflight(project)
    path = write_versioned_json(project.root / "reports", "preflight", report)
    project.audit("preflight_local", {
        "report": project.relative(path), "network": False,
        "ffmpeg": report["tools"]["ffmpeg"]["usable"],
        "gpt_image": report["tools"]["gpt_image"]["usable"],
        "ark_key_defined": report["ark_key_presence"]["defined"],
    })
    return path, report
