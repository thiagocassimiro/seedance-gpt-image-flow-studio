"""Criação de projetos, paths seguros e histórico sem sobrescrita destrutiva."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .errors import DuplicateSubmissionError, ValidationError
from .security import redact_data

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))
}
_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_SHOT_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,31}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def timestamp_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_bytes_new(path: str | Path, data: bytes) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(data)
    return destination


def write_text_new(path: str | Path, text: str) -> Path:
    return write_bytes_new(path, text.encode("utf-8"))


def write_json_new(path: str | Path, value: Any) -> Path:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    return write_text_new(path, text)


def write_versioned_json(directory: str | Path, stem: str, value: Any) -> Path:
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]", "-", stem)
    path = Path(directory) / f"{safe_stem}-{timestamp_tag()}-{uuid.uuid4().hex[:8]}.json"
    return write_json_new(path, value)


def normalize_project_name(name: str) -> str:
    normalized = name.strip().lower().replace("_", "-").replace(" ", "-")
    if not _PROJECT_RE.fullmatch(normalized) or normalized.endswith("-"):
        raise ValidationError("nome do projeto deve usar letras minúsculas, números e hífens, sem paths")
    if normalized.upper() in _WINDOWS_RESERVED:
        raise ValidationError("nome reservado pelo Windows")
    return normalized


def normalize_shot_id(shot_id: str) -> str:
    normalized = shot_id.strip().upper().replace("_", "-")
    if not _SHOT_RE.fullmatch(normalized) or normalized.endswith("-") or normalized in _WINDOWS_RESERVED:
        raise ValidationError("shot ID inválido")
    return normalized


@contextmanager
def exclusive_lock(path: str | Path):
    """Lock local propositalmente conservador; locks stale exigem revisão manual."""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError as exc:
        raise DuplicateSubmissionError(f"operação já está em andamento; revise o lock {lock_path}") from exc
    try:
        os.write(descriptor, canonical_json({"pid": os.getpid(), "created_at": utc_now()}).encode("utf-8"))
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        # Lock é coordenação transitória, não uma versão de produção.
        lock_path.unlink(missing_ok=True)


def _atomic_replace_with_history(path: Path, history_dir: Path, value: Any) -> None:
    if path.exists():
        backup = history_dir / f"{path.stem}-{timestamp_tag()}-{sha256_file(path)[:12]}.json"
        write_bytes_new(backup, path.read_bytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


@dataclass(frozen=True)
class Project:
    studio_root: Path
    name: str

    @property
    def root(self) -> Path:
        return self.studio_root / "projects" / self.name

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @classmethod
    def open(cls, studio_root: str | Path, name: str) -> "Project":
        project = cls(Path(studio_root).resolve(), normalize_project_name(name))
        if not project.manifest_path.is_file():
            raise ValidationError(f"projeto não encontrado ou sem manifesto: {project.root}")
        return project

    def manifest(self) -> dict[str, Any]:
        return read_json(self.manifest_path)

    def resolve(self, relative: str | Path) -> Path:
        candidate = (self.root / relative).resolve() if not Path(relative).is_absolute() else Path(relative).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            raise ValidationError("path fora do projeto não é permitido")
        return candidate

    def relative(self, path: str | Path) -> str:
        return Path(path).resolve().relative_to(self.root.resolve()).as_posix()

    def shot_path(self, shot_id: str) -> Path:
        return self.root / "shots" / f"{normalize_shot_id(shot_id)}.json"

    def shot(self, shot_id: str) -> dict[str, Any]:
        path = self.shot_path(shot_id)
        if not path.is_file():
            raise ValidationError(f"shot não encontrado: {normalize_shot_id(shot_id)}")
        shot = read_json(path)
        if shot.get("id") != normalize_shot_id(shot_id):
            raise ValidationError("ID interno do shot diverge do nome do arquivo")
        return shot

    def list_shots(self) -> list[dict[str, Any]]:
        shots = []
        for path in sorted((self.root / "shots").glob("*.json")):
            shots.append(self.shot(path.stem))
        return shots

    def models_config(self) -> dict[str, Any]:
        return read_json(self.root / "config" / "models.json")

    def pricing_config(self) -> dict[str, Any]:
        return read_json(self.root / "config" / "pricing.json")

    def update_manifest(self, reason: str, updater: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with exclusive_lock(self.root / "locks" / "manifest.lock"):
            current = self.manifest()
            updated = copy.deepcopy(current)
            updater(updated)
            updated["revision"] = int(current.get("revision", 0)) + 1
            updated["updated_at"] = utc_now()
            _atomic_replace_with_history(self.manifest_path, self.root / "history" / "manifest", updated)
        append_audit(self, "manifest_updated", {"reason": reason, "revision": updated["revision"]})
        return updated

    def update_shot(self, shot_id: str, reason: str, updater: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        normalized = normalize_shot_id(shot_id)
        path = self.shot_path(normalized)
        with exclusive_lock(self.root / "locks" / f"shot-{normalized}.lock"):
            current = self.shot(normalized)
            updated = copy.deepcopy(current)
            updater(updated)
            updated["updated_at"] = utc_now()
            _atomic_replace_with_history(path, self.root / "history" / "shots" / normalized, updated)
        append_audit(self, "shot_updated", {"shot_id": normalized, "reason": reason})
        return updated

    def audit(self, event: str, data: dict[str, Any] | None = None) -> None:
        append_audit(self, event, data or {})


def append_audit(project: Project, event: str, data: dict[str, Any]) -> None:
    path = project.root / "logs" / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": utc_now(), "event": event, "data": redact_data(data)}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(record) + "\n")


def _default_shot() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": "SHOT-001",
        "status": "draft",
        "model": "dreamina-seedance-2-0-mini-260615",
        "duration": 5,
        "resolution": "720p",
        "ratio": "16:9",
        "generate_audio": False,
        "watermark": False,
        "attempts": 1,
        "quantity": 1,
        "prompt": "",
        "require_first_last_frames": True,
        "frames": {
            "first_url": None,
            "last_url": None,
            "first_file": None,
            "last_file": None,
            "first_role": "first_frame",
            "last_role": "last_frame"
        },
        "references": [],
        "image_calls": [],
        "image_costs_reconciled": False,
        "notes": "Mini é apenas a preferência econômica não verificada; não há fallback automático para Fast ou 2.5.",
        "created_at": utc_now()
    }


def new_project(studio_root: str | Path, name: str) -> Project:
    root = Path(studio_root).resolve()
    normalized = normalize_project_name(name)
    project = Project(root, normalized)
    if project.root.exists():
        raise ValidationError(f"o projeto já existe; nenhum arquivo foi alterado: {project.root}")
    for filename in ("models.example.json", "pricing.example.json"):
        if not (root / "config" / filename).is_file():
            raise ValidationError(f"configuração modelo ausente: {root / 'config' / filename}")

    directories = [
        "approvals", "characters", "clips/original", "clips/derived", "config", "costs", "delivery",
        "estimates", "frames", "history", "images", "locks", "logs", "qc/frames", "references", "reports",
        "reviews/story", "reviews/frames", "reviews/final", "shots", "style", "tasks", "video_prompts"
    ]
    project.root.mkdir(parents=True, exist_ok=False)
    for directory in directories:
        (project.root / directory).mkdir(parents=True, exist_ok=True)

    shutil.copyfile(root / "config" / "models.example.json", project.root / "config" / "models.json")
    shutil.copyfile(root / "config" / "pricing.example.json", project.root / "config" / "pricing.json")
    write_text_new(project.root / "briefing.md", "# Briefing\n\nDescreva ideia, público, objetivo, duração, proporção, orçamento, música e legendas.\n")
    write_json_new(project.root / "requirements.json", {
        "status": "draft", "duration_seconds": None, "ratio": "16:9", "budget": None,
        "music": None, "subtitles": None, "created_at": utc_now()
    })
    write_text_new(project.root / "story.md", "# Roteiro\n\nAguardando briefing e desenvolvimento. Não gerar imagens antes da aprovação da história.\n")
    write_text_new(project.root / "storyboard.csv", (
        "shot_id,start_seconds,end_seconds,generation_seconds,shot_size,camera_angle,camera_move,"
        "screen_direction,emotion,motion_subject,transition\n"
    ))
    write_json_new(project.root / "style" / "palette.json", {
        "status": "draft", "style": None, "colors": [], "contrast_rules": [],
        "black_and_white_review": {"status": "not_run", "report": None}
    })
    write_json_new(project.root / "edit_plan.json", {
        "schema_version": 1, "clips": [], "include_audio": True, "freeze_last_seconds": 0.0,
        "upscale_1080": True, "canvas": {"width": 1280, "height": 720},
        "delivery_canvas": {"width": 1920, "height": 1080}, "fps": 24,
        "cut_points_seconds": [], "color": {"hue_adjustment": False}
    })
    write_json_new(project.shot_path("SHOT-001"), _default_shot())
    write_text_new(project.root / "video_prompts" / "SHOT-001.md", "# Prompt do SHOT-001\n\nPreencher após a revisão dos frames.\n")
    write_text_new(project.root / "lessons.md", "# Lições aprendidas\n\nRegistrar estilo, prompts, erros e decisões sem apagar o histórico.\n")
    write_json_new(project.manifest_path, {
        "schema_version": 1,
        "project_id": "prj_" + uuid.uuid4().hex[:16],
        "name": normalized,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "revision": 0,
        "stage": "briefing",
        "shots": {"SHOT-001": {"path": "shots/SHOT-001.json", "latest_estimate": None, "latest_frame_review": None}},
        "tasks": {},
        "idempotency_keys": {},
        "images": [],
        "clips": [],
        "actual_costs": [],
        "submission_policy": {"parallel_paid": False, "auto_retry": False, "auto_model_fallback": False}
    })
    append_audit(project, "project_created", {"project": normalized, "paid_operations": False})
    return project
