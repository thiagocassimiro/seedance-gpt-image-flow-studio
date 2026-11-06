"""Redação de segredos e validação de URLs oficiais."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .errors import ValidationError

_SENSITIVE_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
    "signature",
    "credential",
)


def _secret_values() -> list[str]:
    values = []
    for name in ("ARK_API_KEY", "OPENAI_API_KEY"):
        value = os.environ.get(name)
        if value:
            values.append(value)
    return sorted(values, key=len, reverse=True)


def redact_text(value: str) -> str:
    result = value
    for secret in _secret_values():
        result = result.replace(secret, "<redacted>")
    return result


def redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return redact_text(value)
    if not parsed.scheme or not parsed.netloc:
        return redact_text(value)
    hostname = parsed.hostname or ""
    netloc = hostname
    if parsed.port:
        netloc += f":{parsed.port}"
    query = urlencode([(key, "REDACTED") for key, _ in parse_qsl(parsed.query, keep_blank_values=True)])
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))


def redact_data(value: Any) -> Any:
    """Remove segredos de logs/payloads sem alterar o objeto original."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = re.sub(r"[-\s]", "_", str(key).lower())
            if any(part in normalized for part in _SENSITIVE_PARTS) or normalized.startswith("x_tos_"):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = redact_data(item)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_data(item) for item in value]
    if isinstance(value, str):
        redacted = redact_text(value)
        if redacted.startswith(("https://", "http://")):
            return redact_url(redacted)
        return redacted
    return value


def validate_https_url(value: str, field: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValidationError(f"{field} precisa ser uma URL HTTPS válida")
    if parsed.username or parsed.password:
        raise ValidationError(f"{field} não pode conter credenciais na autoridade da URL")


def validate_official_asset_url(value: str, suffixes: list[str], field: str = "asset") -> None:
    validate_https_url(value, field)
    hostname = (urlsplit(value).hostname or "").lower().rstrip(".")
    allowed = any(hostname == suffix.lower() or hostname.endswith("." + suffix.lower()) for suffix in suffixes)
    if not allowed:
        raise ValidationError(
            f"{field} usa host não autorizado; configure somente hospedagem oficial BytePlus: {hostname or 'desconhecido'}"
        )


def validate_task_id(value: str) -> str:
    task_id = value.strip()
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    # IDs remotos também viram nomes de pastas/arquivos; não permitir ADS, pontos ou separadores do Windows.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,127}", task_id) or task_id.upper() in reserved:
        raise ValidationError("task ID inválido ou inseguro para nomes de arquivo no Windows")
    return task_id
