#!/usr/bin/env python3
"""Verifica arquivos publicáveis sem imprimir valores sensíveis."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_SKIP_DIRS = {".git", ".venv", "__pycache__", ".tmp", "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist"}
_TEXT_SUFFIXES = {".md", ".py", ".json", ".toml", ".yml", ".yaml", ".txt", ".csv", ".cff", ".ps1", ".psm1"}
_TEXT_NAMES = {".gitignore", ".gitattributes", "LICENSE", "NOTICE", "CODEOWNERS"}
_PATTERNS = {
    "chave privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "bearer aparentemente real": re.compile(r"Bearer\s+(?!<redacted>)[A-Za-z0-9_.-]{16,}", re.IGNORECASE),
    "assinatura hexadecimal em URL": re.compile(r"(?:X-Tos-Signature|X-Amz-Signature)=[0-9a-fA-F]{16,}"),
    "token com prefixo sk": re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
}


def _allowed_project_file(relative: Path) -> bool:
    return relative.parts[0] != "projects" or relative.as_posix() in {"projects/.gitkeep", "projects/README.md"}


def scan(root: str | Path) -> tuple[int, list[tuple[str, str]]]:
    base = Path(root).resolve()
    checked = 0
    issues: list[tuple[str, str]] = []
    secrets = [os.environ.get(name) for name in ("ARK_API_KEY", "OPENAI_API_KEY")]
    secrets = [value for value in secrets if value]

    for current, directories, files in os.walk(base, topdown=True):
        current_path = Path(current)
        relative_current = current_path.relative_to(base)
        directories[:] = [name for name in directories if name not in _SKIP_DIRS]
        if relative_current.parts and relative_current.parts[0] == "projects":
            directories[:] = []
        for filename in files:
            path = current_path / filename
            relative = path.relative_to(base)
            if not _allowed_project_file(relative):
                continue
            if filename == ".env" or filename.startswith(".env.") or path.suffix.lower() in {".pem", ".key"}:
                issues.append((relative.as_posix(), "arquivo de credencial proibido"))
                continue
            if path.suffix.lower() not in _TEXT_SUFFIXES and filename not in _TEXT_NAMES:
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            checked += 1
            if any(secret and secret in text for secret in secrets):
                issues.append((relative.as_posix(), "valor de credencial presente no ambiente"))
            for category, pattern in _PATTERNS.items():
                if pattern.search(text):
                    issues.append((relative.as_posix(), category))
    return checked, issues


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    checked, issues = scan(root)
    if issues:
        print(f"PUBLICACAO_BLOQUEADA arquivos_verificados={checked} problemas={len(issues)}")
        for filename, category in issues:
            print(f"ARQUIVO={filename} MOTIVO={category}")
        return 1
    print(f"PUBLICACAO_OK arquivos_verificados={checked} problemas=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
