"""Validação e transformações locais de frames via FFmpeg, sem Pillow."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence

from .errors import ToolMissingError, ValidationError
from .project import Project, sha256_file
from .security import redact_text


def image_size(path: str | Path) -> tuple[int, int]:
    source = Path(path)
    with source.open("rb") as handle:
        header = handle.read(32)
        if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
            width, height = struct.unpack(">II", header[16:24])
            if width > 0 and height > 0:
                return width, height
        if header.startswith(b"\xff\xd8"):
            handle.seek(2)
            while True:
                marker_start = handle.read(1)
                if not marker_start:
                    break
                if marker_start != b"\xff":
                    continue
                marker = handle.read(1)
                while marker == b"\xff":
                    marker = handle.read(1)
                if marker in (b"\xd8", b"\xd9") or b"\xd0" <= marker <= b"\xd7":
                    continue
                length_bytes = handle.read(2)
                if len(length_bytes) != 2:
                    break
                length = struct.unpack(">H", length_bytes)[0]
                if length < 2:
                    break
                if marker and marker[0] in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    payload = handle.read(5)
                    if len(payload) == 5:
                        height, width = struct.unpack(">HH", payload[1:5])
                        return width, height
                    break
                handle.seek(length - 2, 1)
    raise ValidationError(f"formato de imagem não suportado ou dimensões ilegíveis: {source}")


def _ratio(value: str) -> Fraction:
    try:
        width, height = value.split(":", 1)
        return Fraction(int(width), int(height))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValidationError(f"proporção inválida: {value}") from exc


def compare_frame_dimensions(first: str | Path, last: str | Path, expected_ratio: str = "16:9") -> dict[str, Any]:
    first_size = image_size(first)
    last_size = image_size(last)
    errors = []
    if first_size != last_size:
        errors.append(f"dimensões divergentes: primeiro={first_size}, último={last_size}")
    actual_ratio = Fraction(*first_size)
    if actual_ratio != _ratio(expected_ratio):
        errors.append(f"proporção {first_size[0]}:{first_size[1]} não corresponde a {expected_ratio}")
    return {
        "ok": not errors,
        "first": {"path": str(first), "width": first_size[0], "height": first_size[1], "sha256": sha256_file(first)},
        "last": {"path": str(last), "width": last_size[0], "height": last_size[1], "sha256": sha256_file(last)},
        "expected_ratio": expected_ratio,
        "errors": errors,
    }


def validate_shot_frames(project: Project, shot: dict[str, Any]) -> dict[str, Any]:
    frames = shot.get("frames", {})
    first = frames.get("first_file")
    last = frames.get("last_file")
    if not first or not last:
        return {
            "ok": False,
            "checked": False,
            "errors": ["first_file e last_file locais são necessários para validar dimensões"],
            "note": "URLs remotas não são baixadas pelo dry-run."
        }
    result = compare_frame_dimensions(project.resolve(first), project.resolve(last), str(shot.get("ratio", "16:9")))
    result["checked"] = True
    return result


def ensure_new_output(path: str | Path) -> Path:
    output = Path(path)
    if output.exists():
        raise ValidationError(f"saída já existe e não será sobrescrita: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def require_tool(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise ToolMissingError(f"{name} não foi encontrado no PATH; nenhuma instalação foi tentada")
    return executable


def run_media_command(command: Sequence[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command), shell=False, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationError(f"comando de mídia excedeu {timeout}s; revise os arquivos antes de repetir") from exc
    if result.returncode != 0:
        message = redact_text(result.stderr[-4000:] or result.stdout[-4000:])
        raise ValidationError(f"FFmpeg retornou {result.returncode}: {message}")
    return result


def build_contact_sheet_command(first: str | Path, last: str | Path, output: str | Path, executable: str = "ffmpeg") -> list[str]:
    tile = "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    return [
        executable, "-hide_banner", "-n", "-i", str(first), "-i", str(last),
        "-filter_complex", f"[0:v]{tile}[a];[1:v]{tile}[b];[a][b]hstack=inputs=2[out]",
        "-map", "[out]", "-frames:v", "1", "-update", "1", str(output),
    ]


def build_overlay_command(first: str | Path, last: str | Path, output: str | Path, opacity: float = 0.5, executable: str = "ffmpeg") -> list[str]:
    if not 0 < opacity < 1:
        raise ValidationError("opacity deve ficar entre 0 e 1")
    return [
        executable, "-hide_banner", "-n", "-i", str(first), "-i", str(last),
        "-filter_complex", f"[0:v][1:v]blend=all_mode=normal:all_opacity={opacity:.3f}[out]",
        "-map", "[out]", "-frames:v", "1", "-update", "1", str(output),
    ]


def build_grayscale_command(source: str | Path, output: str | Path, executable: str = "ffmpeg") -> list[str]:
    return [executable, "-hide_banner", "-n", "-i", str(source), "-vf", "hue=s=0", "-frames:v", "1", "-update", "1", str(output)]


def build_extract_frame_command(source: str | Path, timestamp: float, output: str | Path, executable: str = "ffmpeg") -> list[str]:
    if timestamp < 0:
        raise ValidationError("timestamp não pode ser negativo")
    return [executable, "-hide_banner", "-n", "-ss", f"{timestamp:.3f}", "-i", str(source), "-frames:v", "1", "-update", "1", str(output)]


def contact_sheet(first: str | Path, last: str | Path, output: str | Path) -> Path:
    destination = ensure_new_output(output)
    run_media_command(build_contact_sheet_command(first, last, destination, require_tool("ffmpeg")))
    return destination


def overlay_frames(first: str | Path, last: str | Path, output: str | Path, opacity: float = 0.5) -> Path:
    comparison = compare_frame_dimensions(first, last)
    # A sobreposição exige apenas dimensões iguais; a proporção é validada separadamente pelo shot.
    if comparison["first"]["width"] != comparison["last"]["width"] or comparison["first"]["height"] != comparison["last"]["height"]:
        raise ValidationError("a sobreposição exige frames com as mesmas dimensões")
    destination = ensure_new_output(output)
    run_media_command(build_overlay_command(first, last, destination, opacity, require_tool("ffmpeg")))
    return destination


def grayscale_frame(source: str | Path, output: str | Path) -> Path:
    destination = ensure_new_output(output)
    run_media_command(build_grayscale_command(source, destination, require_tool("ffmpeg")))
    return destination


def extract_frame(source: str | Path, timestamp: float, output: str | Path) -> Path:
    destination = ensure_new_output(output)
    run_media_command(build_extract_frame_command(source, timestamp, destination, require_tool("ffmpeg")))
    return destination
