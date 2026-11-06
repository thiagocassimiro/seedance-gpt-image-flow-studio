"""Montagem local: cortes, freeze, cor leve, concat e Lanczos, sem alterar originais."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .frames import ensure_new_output, require_tool, run_media_command
from .project import Project, read_json, sha256_file, timestamp_tag, utc_now


def _time(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
        raise ValidationError(f"{field} precisa ser finito e não negativo")
    return f"{float(value):.3f}"


def _bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ValidationError(f"{field} precisa ser booleano")
    return value


def _canvas(plan: dict[str, Any], field: str, default: tuple[int, int]) -> tuple[int, int]:
    value = plan.get(field, {})
    width = value.get("width", default[0])
    height = value.get("height", default[1])
    if isinstance(width, bool) or isinstance(height, bool) or not isinstance(width, int) or not isinstance(height, int):
        raise ValidationError(f"{field} precisa de largura/altura inteiras")
    if not 16 <= width <= 7680 or not 16 <= height <= 4320 or width % 2 or height % 2:
        raise ValidationError(f"{field} precisa de dimensões pares dentro dos limites")
    return width, height


def _fit(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )


def build_assembly_command(plan: dict[str, Any], output: str | Path, executable: str = "ffmpeg") -> list[str]:
    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValidationError("edit_plan.clips precisa conter ao menos um clipe")
    hue_adjustment = _bool(plan.get("color", {}).get("hue_adjustment", False), "color.hue_adjustment")
    if hue_adjustment:
        raise ValidationError("ajuste de matiz está desabilitado; somente brilho e saturação leves")
    include_audio = _bool(plan.get("include_audio", True), "include_audio")
    upscale = _bool(plan.get("upscale_1080", True), "upscale_1080")
    canvas = _canvas(plan, "canvas", (1280, 720))
    delivery_canvas = _canvas(plan, "delivery_canvas", (1920, 1080))
    fps = plan.get("fps", 24)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(float(fps)) or not 1 <= fps <= 120:
        raise ValidationError("fps precisa ser finito e ficar entre 1 e 120")

    command = [executable, "-hide_banner", "-n"]
    filters: list[str] = []
    video_labels = []
    audio_labels = []
    for index, clip in enumerate(clips):
        path = str(clip.get("path") or "")
        if not path:
            raise ValidationError(f"clips[{index}].path ausente")
        command.extend(["-i", path])
        start = _time(clip.get("start", 0), f"clips[{index}].start")
        trim = f"trim=start={start}"
        atrim = f"atrim=start={start}"
        end_value = None
        if clip.get("end") is not None:
            end_value = _time(clip["end"], f"clips[{index}].end")
            if float(end_value) <= float(start):
                raise ValidationError(f"clips[{index}].end precisa ser maior que start")
            trim += f":end={end_value}"
            atrim += f":end={end_value}"
        brightness = clip.get("brightness", 0.0)
        saturation = clip.get("saturation", 1.0)
        if not math.isfinite(float(brightness)) or not -0.1 <= float(brightness) <= 0.1:
            raise ValidationError("brilho deve ser finito e permanecer leve (-0.1 a 0.1)")
        if not math.isfinite(float(saturation)) or not 0.5 <= float(saturation) <= 1.5:
            raise ValidationError("saturação deve ser finita e permanecer leve (0.5 a 1.5)")
        filters.append(
            f"[{index}:v]{trim},setpts=PTS-STARTPTS,"
            f"eq=brightness={float(brightness):.4f}:saturation={float(saturation):.4f},"
            f"{_fit(*canvas)},fps={float(fps):g},format=yuv420p,setsar=1[v{index}]"
        )
        video_labels.append(f"[v{index}]")
        if include_audio:
            has_audio = _bool(clip.get("has_audio", True), f"clips[{index}].has_audio")
            if has_audio:
                filters.append(
                    f"[{index}:a]{atrim},asetpts=PTS-STARTPTS,aresample=48000,"
                    f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
                )
            else:
                duration_value = clip.get("duration")
                if duration_value is None and end_value is not None:
                    duration_value = float(end_value) - float(start)
                if duration_value is None or not math.isfinite(float(duration_value)) or float(duration_value) <= 0:
                    raise ValidationError("clipe sem áudio precisa de end ou duration para gerar silêncio na montagem")
                duration_text = _time(duration_value, f"clips[{index}].duration")
                filters.append(
                    f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={duration_text},"
                    f"asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
                )
            audio_labels.append(f"[a{index}]")
    concat_inputs = "".join(label for pair in zip(video_labels, audio_labels) for label in pair) if include_audio else "".join(video_labels)
    filters.append(f"{concat_inputs}concat=n={len(clips)}:v=1:a={1 if include_audio else 0}[vc]{'' if not include_audio else '[ac]'}")
    video_source = "vc"
    freeze = float(plan.get("freeze_last_seconds", 0.0))
    if not math.isfinite(freeze) or freeze < 0:
        raise ValidationError("freeze_last_seconds precisa ser finito e não negativo")
    if freeze > 0:
        filters.append(f"[{video_source}]tpad=stop_mode=clone:stop_duration={freeze:.3f}[vf]")
        video_source = "vf"
        if include_audio:
            filters.append(f"[ac]apad=pad_dur={freeze:.3f},aresample=48000[af]")
    elif include_audio:
        filters.append("[ac]anull[af]")
    if upscale:
        filters.append(f"[{video_source}]{_fit(*delivery_canvas)},unsharp=5:5:0.3:5:5:0.0,setsar=1[vout]")
    else:
        filters.append(f"[{video_source}]null[vout]")
    command.extend(["-filter_complex", ";".join(filters), "-map", "[vout]"])
    if include_audio:
        command.extend(["-map", "[af]"])
    command.extend([
        "-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
    ])
    if include_audio:
        command.extend(["-c:a", "flac"])
    command.append(str(output))
    return command


def build_delivery_command(master: str | Path, output: str | Path, executable: str = "ffmpeg") -> list[str]:
    return [
        executable, "-hide_banner", "-n", "-i", str(master),
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", str(output),
    ]


def assemble_project(project: Project, dry_run: bool = False) -> dict[str, Any]:
    plan = read_json(project.root / "edit_plan.json")
    resolved_plan = dict(plan)
    resolved_clips = []
    original_hashes: dict[str, str] = {}
    for clip in plan.get("clips", []):
        source = project.resolve(clip["path"])
        if not source.is_file():
            raise ValidationError(f"clipe do plano não encontrado: {source}")
        original_hashes[project.relative(source)] = sha256_file(source)
        resolved = {**clip, "path": str(source)}
        if not dry_run:
            from .qc import probe_media
            probe = probe_media(source)
            resolved["has_audio"] = any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))
        resolved_clips.append(resolved)
    resolved_plan["clips"] = resolved_clips
    tag = timestamp_tag()
    master = ensure_new_output(project.root / "clips" / "derived" / f"master-{tag}.mkv")
    delivery = ensure_new_output(project.root / "delivery" / f"{project.name}-{tag}.mp4")
    ffmpeg = "ffmpeg" if dry_run else require_tool("ffmpeg")
    master_command = build_assembly_command(resolved_plan, master, ffmpeg)
    delivery_command = build_delivery_command(master, delivery, ffmpeg)
    if dry_run:
        return {
            "executed": False, "master_command": master_command, "delivery_command": delivery_command,
            "master": project.relative(master), "delivery": project.relative(delivery),
            "note": "Diretórios podem ter sido preparados; nenhum arquivo de mídia foi criado ou alterado."
        }

    def verify_originals() -> None:
        for relative, digest in original_hashes.items():
            if sha256_file(project.resolve(relative)) != digest:
                raise ValidationError(f"um clipe original mudou durante a montagem: {relative}")

    run_media_command(master_command)
    verify_originals()
    master_record = {
        "kind": "lossless_master", "path": project.relative(master),
        "sha256": sha256_file(master), "created_at": utc_now(),
    }
    try:
        def update_master(manifest: dict[str, Any]) -> None:
            manifest.setdefault("clips", []).append(master_record)
            manifest["last_assembly"] = {"master": master_record["path"], "delivery": None, "created_at": master_record["created_at"]}
        project.update_manifest("lossless_master_recorded", update_master)
    except Exception as exc:
        raise ValidationError(f"master foi criado, mas seu registro falhou; preserve {master_record['path']}: {exc}") from exc

    try:
        run_media_command(delivery_command)
    except Exception:
        project.audit("assembly_delivery_failed", {"master": master_record["path"], "recovery": "master já registrado; não recrie automaticamente"})
        raise
    verify_originals()
    delivery_record = {
        "kind": "delivery", "path": project.relative(delivery),
        "sha256": sha256_file(delivery), "created_at": utc_now(),
    }

    def update_delivery(manifest: dict[str, Any]) -> None:
        manifest.setdefault("clips", []).append(delivery_record)
        manifest["last_assembly"] = {
            "master": master_record["path"], "delivery": delivery_record["path"], "created_at": delivery_record["created_at"],
        }

    project.update_manifest("assembly_completed", update_delivery)
    project.audit("assembly_completed", {"master": master_record["path"], "delivery": delivery_record["path"]})
    return {"executed": True, "master": master_record, "delivery": delivery_record, "originals_verified_unchanged": True}
