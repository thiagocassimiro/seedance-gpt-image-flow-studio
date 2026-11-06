"""QC técnico e extração de frames; não finge revisão de movimento ou escuta."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .frames import extract_frame, require_tool, run_media_command
from .project import Project, read_json, timestamp_tag, utc_now, write_versioned_json


def probe_media(path: Path) -> dict[str, Any]:
    executable = require_tool("ffprobe")
    result = run_media_command([
        executable, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)
    ])
    return json.loads(result.stdout)


def decode_check(path: Path) -> dict[str, Any]:
    executable = require_tool("ffmpeg")
    run_media_command([executable, "-hide_banner", "-v", "error", "-i", str(path), "-f", "null", "-"])
    return {"full_decode_completed": True, "decode_errors": []}


def _duration(probe: dict[str, Any]) -> float:
    try:
        return max(0.0, float(probe.get("format", {}).get("duration", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _sample_times(duration: float, cut_points: list[float], fps: float = 24.0) -> list[float]:
    times = {0.0, max(0.0, duration / 2), max(0.0, duration - 1 / fps)}
    for cut in cut_points:
        for index in range(3, 0, -1):
            times.add(max(0.0, cut - index / fps))
            times.add(min(duration, cut + (index - 1) / fps))
    return sorted(time for time in times if time <= duration)


def inspect_clip(project: Project, clip: dict[str, Any], output_dir: Path, cut_points: list[float]) -> dict[str, Any]:
    path = project.resolve(clip["path"])
    report: dict[str, Any] = {
        "clip": clip["path"], "kind": clip.get("kind"), "sha256_expected": clip.get("sha256"),
        "motion_reviewed": False, "audio_reviewed": False,
        "limitations": [
            "Frames extraídos não comprovam avaliação da sensação de movimento.",
            "Presença e decodificação de áudio não equivalem a escuta ou avaliação de sincronia."
        ],
    }
    try:
        probe = probe_media(path)
        report["probe"] = probe
        report["audio_present"] = any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))
        report.update(decode_check(path))
        frames = []
        for index, seconds in enumerate(_sample_times(_duration(probe), cut_points)):
            destination = output_dir / f"frame-{index:03d}-{seconds:.3f}.png"
            extract_frame(path, seconds, destination)
            frames.append({"path": project.relative(destination), "seconds": seconds})
        report["extracted_frames"] = frames
        report["static_frame_review_required"] = True
        report["status"] = "technical_checks_completed"
    except Exception as exc:
        report["status"] = "check_incomplete"
        report["errors"] = [str(exc)]
    return report


def run_qc(project: Project) -> tuple[Path, dict[str, Any]]:
    manifest = project.manifest()
    clips = manifest.get("clips", [])
    tag = timestamp_tag()
    plan_path = project.root / "edit_plan.json"
    cut_points = read_json(plan_path).get("cut_points_seconds", []) if plan_path.is_file() else []
    report = {
        "schema_version": 1,
        "created_at": utc_now(),
        "project": project.name,
        "status": "pending_no_clips" if not clips else "completed_with_limitations",
        "clips": [],
        "motion_reviewed": False,
        "audio_reviewed": False,
        "network_used": False,
        "note": "A revisão humana dos frames, do movimento e do som continua necessária.",
    }
    if clips:
        output_dir = project.root / "qc" / "frames" / tag
        output_dir.mkdir(parents=True, exist_ok=True)
        report["clips"] = [inspect_clip(project, clip, output_dir, cut_points) for clip in clips]
        if any(item.get("status") == "check_incomplete" for item in report["clips"]):
            report["status"] = "incomplete"
    path = write_versioned_json(project.root / "qc", "qc", report)

    def update(value: dict[str, Any]) -> None:
        value["last_qc"] = {"path": project.relative(path), "created_at": report["created_at"], "status": report["status"]}

    project.update_manifest("technical_qc_recorded", update)
    project.audit("technical_qc_recorded", {"report": project.relative(path), "clips": len(clips)})
    return path, report
