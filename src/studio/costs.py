"""Estimativas determinísticas; preço ausente nunca vira zero."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .project import (
    Project,
    read_json,
    sha256_file,
    sha256_json,
    utc_now,
    write_versioned_json,
)


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError(f"{field} precisa ser um inteiro positivo")
    return value


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{field} não é numérico") from exc
    if not result.is_finite() or result < 0:
        raise ValidationError(f"{field} precisa ser finito e não negativo")
    return result


def _known_price(entry: dict[str, Any], value_key: str) -> tuple[Decimal | None, str | None, list[str]]:
    value = entry.get(value_key)
    if value is None:
        return None, None, ["preço não informado (null não significa gratuito)"]
    issues = []
    for field in ("currency", "effective_date", "retrieved_at", "source_url"):
        if not entry.get(field):
            issues.append(f"metadado obrigatório ausente: {field}")
    if issues:
        return None, None, issues
    price = _decimal(value, value_key)
    return price, str(entry["currency"]).upper(), issues


def estimate_cost(shot: dict[str, Any], pricing: dict[str, Any]) -> dict[str, Any]:
    duration = _positive_int(shot.get("duration"), "duration")
    attempts = _positive_int(shot.get("attempts", 1), "attempts")
    quantity = _positive_int(shot.get("quantity", 1), "quantity")
    model = str(shot.get("model") or "")
    resolution = str(shot.get("resolution") or "")
    seconds = Decimal(duration * attempts * quantity)

    model_pricing = pricing.get("video_models", {}).get(model)
    resolution_pricing = (model_pricing or {}).get("resolutions", {}).get(resolution)
    video_issues: list[str] = []
    video_price = None
    currency = None
    if not model:
        video_issues.append("modelo não informado")
    elif model_pricing is None:
        video_issues.append("modelo não existe em pricing.json; nenhum fallback foi aplicado")
    elif resolution_pricing is None:
        video_issues.append(f"preço para {resolution} não configurado")
    else:
        video_price, currency, video_issues = _known_price(resolution_pricing, "price_per_second")

    video_amount = video_price * seconds if video_price is not None else None
    video = {
        "known": video_amount is not None,
        "model": model,
        "resolution": resolution,
        "duration_seconds_per_attempt": duration,
        "attempts": attempts,
        "quantity": quantity,
        "billable_seconds": str(seconds),
        "price_per_second": str(video_price) if video_price is not None else None,
        "amount": str(video_amount) if video_amount is not None else None,
        "issues": video_issues,
    }

    image_items = []
    image_issues: list[str] = []
    image_amount = Decimal("0")
    if shot.get("image_costs_reconciled") is not True:
        image_issues.append("custos de imagem ainda não foram reconciliados com manifest.images")
    image_calls = shot.get("image_calls")
    if not isinstance(image_calls, list):
        image_issues.append("image_calls ausente; declare [] explicitamente ou precifique cada chamada")
        image_calls = []
    for index, call in enumerate(image_calls):
        image_model = call.get("model")
        quality = call.get("quality", "low")
        count = _positive_int(call.get("count", 1), f"image_calls[{index}].count")
        entry = pricing.get("image_models", {}).get(image_model, {}).get("qualities", {}).get(quality)
        issues: list[str] = []
        price = None
        image_currency = None
        if entry is None:
            issues.append("preço da chamada de imagem não configurado")
        else:
            price, image_currency, issues = _known_price(entry, "price_per_image")
        amount = price * count if price is not None else None
        if amount is not None:
            image_amount += amount
        if image_currency and currency and image_currency != currency:
            issues.append("moedas diferentes não podem ser somadas")
        image_items.append({
            "model": image_model, "quality": quality, "count": count,
            "price_per_image": str(price) if price is not None else None,
            "amount": str(amount) if amount is not None else None,
            "currency": image_currency, "issues": issues,
        })
        image_issues.extend(issues)
        if image_currency and not currency:
            currency = image_currency

    images_known = not image_issues and all(item["amount"] is not None for item in image_items)
    total_known = video["known"] and images_known
    total_amount = video_amount + image_amount if total_known and video_amount is not None else None
    return {
        "schema_version": 1,
        "shot_id": shot.get("id"),
        "shot_sha256": sha256_json(shot),
        "created_at": utc_now(),
        "known": total_known,
        "currency": currency if total_known else None,
        "video": video,
        "images": {
            "known": images_known,
            "calls": image_items,
            "amount": str(image_amount) if images_known else None,
            "issues": image_issues,
            "note": "Uma lista vazia declara que esta estimativa não inclui imagens; não prova que imagens sejam gratuitas."
        },
        "total_amount": str(total_amount) if total_amount is not None else None,
        "pricing_source": pricing.get("source"),
        "auto_retry_included": False,
        "note": "attempts limita o orçamento planejado; cada submissão real exige comando e aprovação próprios."
    }


def estimate_single_image(model: str, quality: str, pricing: dict[str, Any]) -> dict[str, Any]:
    entry = pricing.get("image_models", {}).get(model, {}).get("qualities", {}).get(quality)
    issues: list[str] = []
    price = None
    currency = None
    if entry is None:
        issues.append("preço da imagem não configurado para modelo/qualidade")
    else:
        price, currency, issues = _known_price(entry, "price_per_image")
    return {
        "known": price is not None and currency is not None,
        "model": model, "quality": quality, "count": 1,
        "price_per_image": str(price) if price is not None else None,
        "amount": str(price) if price is not None else None,
        "currency": currency, "issues": issues, "pricing_source": pricing.get("source"),
    }


def save_estimate(project: Project, shot: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    estimate = estimate_cost(shot, project.pricing_config())
    shot_id = str(shot["id"])
    path = write_versioned_json(project.root / "estimates" / shot_id, shot_id, estimate)
    digest = sha256_file(path)
    relative = project.relative(path)

    def update(manifest: dict[str, Any]) -> None:
        entry = manifest["shots"].setdefault(shot_id, {"path": f"shots/{shot_id}.json"})
        entry["latest_estimate"] = {"path": relative, "sha256": digest, "known": estimate["known"]}

    project.update_manifest("estimate_recorded", update)
    project.audit("cost_estimated", {
        "shot_id": shot_id, "path": relative, "known": estimate["known"],
        "amount": estimate["total_amount"], "currency": estimate["currency"]
    })
    return path, estimate


def load_estimate(project: Project, path: str | Path) -> tuple[Path, dict[str, Any]]:
    estimate_path = project.resolve(path)
    estimate = read_json(estimate_path)
    return estimate_path, estimate


def latest_estimate(project: Project, shot_id: str) -> tuple[Path, dict[str, Any]]:
    entry = project.manifest().get("shots", {}).get(shot_id, {}).get("latest_estimate")
    if not entry:
        raise ValidationError("nenhuma estimativa registrada para o shot")
    path = project.resolve(entry["path"])
    if sha256_file(path) != entry["sha256"]:
        raise ValidationError("a estimativa foi alterada; gere uma nova versão e nova aprovação")
    return path, read_json(path)


def write_cost_report(project: Project) -> Path:
    entries = project.manifest().get("actual_costs", [])
    known = [item for item in entries if item.get("amount") is not None and item.get("currency")]
    currencies = {item["currency"] for item in known}
    totals: dict[str, str] = {}
    if len(currencies) <= 1:
        total = sum((_decimal(item["amount"], "actual_cost") for item in known), Decimal("0"))
        if currencies:
            totals[next(iter(currencies))] = str(total)
    report = {
        "created_at": utc_now(),
        "entries": entries,
        "totals": totals if len(currencies) <= 1 else None,
        "issues": ["Há custos sem valor/moeda ou com moedas incompatíveis."] if len(known) != len(entries) or len(currencies) > 1 else [],
        "note": "Custos reais devem ser reconciliados com a cobrança oficial; estimativas não são faturas."
    }
    return write_versioned_json(project.root / "costs", "report", report)


def record_actual_cost(
    project: Project, task_id: str | None, amount: str, currency: str,
    source: str, reference: str,
) -> dict[str, Any]:
    """Reconcilia custo real informado pela fatura, sem inferi-lo da estimativa."""
    if not source.strip() or not reference.strip():
        raise ValidationError("fonte e referência da fatura são obrigatórias")
    value = _decimal(amount, "amount")
    code = currency.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValidationError("currency precisa ser um código de três letras")
    if task_id:
        from .security import validate_task_id
        task_id = validate_task_id(task_id)
        if task_id not in project.manifest().get("tasks", {}):
            raise ValidationError("task ID não existe no manifesto")
    identity = {"task_id": task_id, "reference": reference.strip()}
    entry_id = "cost_" + sha256_json(identity)[:20]
    for existing in project.manifest().get("actual_costs", []):
        if existing.get("entry_id") == entry_id:
            return {**existing, "duplicate_ignored": True}
    entry = {
        "entry_id": entry_id, "task_id": task_id, "amount": str(value), "currency": code,
        "source": source.strip(), "reference": reference.strip(), "recorded_at": utc_now(),
        "origin": "manual_billing_reconciliation",
    }

    def update(manifest: dict[str, Any]) -> None:
        manifest.setdefault("actual_costs", []).append(entry)

    project.update_manifest("actual_cost_reconciled", update)
    project.audit("actual_cost_reconciled", {"entry_id": entry_id, "task_id": task_id, "amount": str(value), "currency": code})
    return entry
