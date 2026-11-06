"""Cliente BytePlus ModelArk sem retries e ledger anti-duplicação."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode, urljoin, urlsplit

from .errors import AmbiguousSubmissionError, DuplicateSubmissionError, StudioError, ValidationError
from .project import (
    Project,
    exclusive_lock,
    read_json,
    redact_data,
    sha256_file,
    sha256_json,
    timestamp_tag,
    utc_now,
    write_versioned_json,
)
from .security import redact_text, validate_https_url, validate_image_data_url, validate_official_asset_url, validate_task_id

Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None, float], Any]
DownloadTransport = Callable[[str], bytes]
_ACTIVE_STATES = {"submitting", "submitted", "queued", "running", "pending", "ambiguous", "unknown"}
_SUCCESS_STATES = {"succeeded", "success", "completed"}


class ArkHTTPError(StudioError):
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = redact_data(body)
        super().__init__(f"BytePlus retornou HTTP {status}: {json.dumps(self.body, ensure_ascii=False)}")


class ArkNetworkError(StudioError):
    pass


def validate_models_config(config: dict[str, Any]) -> None:
    if config.get("provider") != "byteplus_modelark":
        raise ValidationError("provider precisa ser byteplus_modelark; intermediários são proibidos")
    endpoint = str(config.get("endpoint_base") or "")
    expected = f"https://ark.{config.get('region')}.bytepluses.com"
    if config.get("region") != "ap-southeast" or endpoint != expected:
        raise ValidationError("região/endpoint não confirmados para esta configuração; revise a documentação BytePlus")
    if config.get("tasks_path") != "/api/v3/contents/generations/tasks":
        raise ValidationError("tasks_path diverge do endpoint oficial configurado")
    if config.get("credential_env") != "ARK_API_KEY":
        raise ValidationError("a credencial deve vir exclusivamente de ARK_API_KEY")
    safety = config.get("safety", {})
    for field in ("allow_paid_submissions", "allow_parallel_paid", "send_idempotency_header"):
        if type(safety.get(field, False)) is not bool:
            raise ValidationError(f"safety.{field} precisa ser booleano; strings não são aceitas")
    if safety.get("allow_parallel_paid") is not False:
        raise ValidationError("allow_parallel_paid precisa permanecer false nesta versão")
    suffixes = safety.get("allowed_asset_host_suffixes")
    if not isinstance(suffixes, list) or not suffixes:
        raise ValidationError("configure os sufixos oficiais de assets")
    models = config.get("models")
    if not isinstance(models, dict) or not models:
        raise ValidationError("nenhum modelo configurado")
    for model_id, definition in models.items():
        if definition.get("id") != model_id:
            raise ValidationError(f"ID divergente no modelo {model_id}")
        if type(definition.get("enabled_for_submission", False)) is not bool:
            raise ValidationError(f"enabled_for_submission precisa ser booleano em {model_id}")


def model_definition(config: dict[str, Any], model_id: str) -> dict[str, Any]:
    validate_models_config(config)
    definition = config.get("models", {}).get(model_id)
    if definition is None:
        raise ValidationError(f"modelo não configurado: {model_id}; nenhuma troca automática foi feita")
    return definition


def _asset(kind: str, url: str, role: str, config: dict[str, Any], field: str) -> dict[str, Any]:
    if kind not in {"image_url", "video_url", "audio_url"}:
        raise ValidationError(f"tipo de asset inválido em {field}: {kind}")
    if not role.strip():
        raise ValidationError(f"role vazio em {field}")
    if kind == "image_url" and url.startswith("data:image/"):
        validate_image_data_url(url, field)
    else:
        validate_official_asset_url(url, config["safety"]["allowed_asset_host_suffixes"], field)
    return {"type": kind, kind: {"url": url}, "role": role}


def _strict_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ValidationError(f"{field} precisa ser booleano; strings não são aceitas")
    return value


def build_payload(shot: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    model_id = str(shot.get("model") or "")
    definition = model_definition(config, model_id)
    prompt = str(shot.get("prompt") or "").strip()
    if not prompt:
        raise ValidationError("prompt do shot está vazio")
    duration = shot.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration < 1:
        raise ValidationError("duration precisa ser um inteiro positivo")
    supported_durations = definition.get("supported_durations")
    if supported_durations is not None and duration not in supported_durations:
        raise ValidationError(f"duração {duration}s não consta como suportada para {model_id}")
    resolution = str(shot.get("resolution") or "")
    supported_resolutions = definition.get("supported_resolutions")
    if supported_resolutions is not None and resolution not in supported_resolutions:
        raise ValidationError(f"resolução {resolution} não consta como suportada para {model_id}")
    ratio = str(shot.get("ratio") or "")
    if not ratio or ratio == "adaptive":
        raise ValidationError("ratio explícito é obrigatório neste workflow")

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    frames = shot.get("frames", {})
    first_url = frames.get("first_url")
    last_url = frames.get("last_url")
    require_frames = _strict_bool(shot.get("require_first_last_frames", True), "require_first_last_frames")
    if require_frames and (not first_url or not last_url):
        raise ValidationError("primeiro e último frames precisam de URLs oficiais; nenhum host improvisado é usado")
    if first_url:
        content.append(_asset("image_url", first_url, str(frames.get("first_role") or "first_frame"), config, "first_url"))
    if last_url:
        content.append(_asset("image_url", last_url, str(frames.get("last_role") or "last_frame"), config, "last_url"))
    references = shot.get("references", [])
    if not isinstance(references, list):
        raise ValidationError("references precisa ser uma lista")
    for index, reference in enumerate(references):
        kind = reference.get("type", "image_url")
        content.append(_asset(
            kind, str(reference.get("url") or ""), str(reference.get("role") or "reference_image"),
            config, f"references[{index}]",
        ))

    return {
        "model": model_id,
        "content": content,
        "generate_audio": _strict_bool(shot.get("generate_audio", False), "generate_audio"),
        "ratio": ratio,
        "duration": duration,
        "resolution": resolution,
        "watermark": _strict_bool(shot.get("watermark", False), "watermark"),
    }


def idempotency_key(project_id: str, shot_id: str, payload: dict[str, Any]) -> str:
    digest = sha256_json({"project_id": project_id, "shot_id": shot_id, "payload": payload})
    return "stv1_" + digest


def dry_run_payload(project: Project, shot: dict[str, Any]) -> dict[str, Any]:
    config = project.models_config()
    payload = build_payload(shot, config)
    key = idempotency_key(project.manifest()["project_id"], str(shot["id"]), payload)
    definition = model_definition(config, str(shot["model"]))
    return {
        "network_request_sent": False,
        "method": "POST (não executado)",
        "url": config["endpoint_base"] + config["tasks_path"],
        "headers": {"Content-Type": "application/json", "Authorization": "Bearer <redacted>"},
        "payload": redact_data(payload),
        "payload_sha256": sha256_json(payload),
        "idempotency_key": key,
        "model_availability": definition.get("availability"),
        "enabled_for_submission": definition.get("enabled_for_submission", False),
        "paid_submissions_enabled": config["safety"].get("allow_paid_submissions", False),
        "warnings": [
            "Dry-run local: nenhuma chamada de rede ou geração foi executada.",
            "Disponibilidade, parâmetros e preço precisam ser confirmados antes de uma operação paga."
        ],
    }


class _SameHostHTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, original_url: str):
        self.original_host = (urlsplit(original_url).hostname or "").lower()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urljoin(req.full_url, newurl)
        validate_https_url(destination, "redirect da API")
        if (urlsplit(destination).hostname or "").lower() != self.original_host:
            raise ArkNetworkError("redirect da API para outro host foi bloqueado")
        return super().redirect_request(req, fp, code, msg, headers, destination)


class _OfficialAssetRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, suffixes: list[str]):
        self.suffixes = suffixes

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urljoin(req.full_url, newurl)
        validate_official_asset_url(destination, self.suffixes, "redirect do download")
        return super().redirect_request(req, fp, code, msg, headers, destination)


class ArkClient:
    """Uma tentativa por chamada; não há retry, fallback ou cancelamento implícito."""

    def __init__(
        self,
        config: dict[str, Any],
        transport: Transport | None = None,
        download_transport: DownloadTransport | None = None,
        timeout: float = 60.0,
    ):
        validate_models_config(config)
        self.config = config
        self.transport = transport
        self.download_transport = download_transport
        self.timeout = timeout

    @property
    def endpoint(self) -> str:
        return self.config["endpoint_base"] + self.config["tasks_path"]

    def _api_key(self) -> str:
        value = os.environ.get("ARK_API_KEY")
        if not value:
            raise ValidationError("ARK_API_KEY não está definida no processo")
        return value

    def _request(
        self, method: str, url: str, body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key()}"}
        if extra_headers:
            headers.update(extra_headers)
        if self.transport:
            result = self.transport(method, url, headers, body, self.timeout)
            status, response_body = result if isinstance(result, tuple) else (200, result)
            if not 200 <= int(status) < 300:
                raise ArkHTTPError(int(status), response_body)
            return response_body
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            opener = urllib.request.build_opener(_SameHostHTTPSRedirect(url))
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
                if len(raw) > 16 * 1024 * 1024:
                    raise ValidationError("resposta da API excedeu o limite local de 16 MiB")
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read(1024 * 1024)
            try:
                response_body = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                response_body = {"message": raw.decode("utf-8", errors="replace")}
            raise ArkHTTPError(exc.code, response_body) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            raise ArkNetworkError(redact_text(str(exc))) from exc
        except json.JSONDecodeError as exc:
            raise ValidationError("resposta da API não era JSON válido") from exc

    def create_task(self, payload: dict[str, Any], key: str) -> Any:
        # A chave é local por padrão; header remoto só é enviado se explicitamente validado na configuração.
        extra = {"X-Idempotency-Key": key} if self.config["safety"].get("send_idempotency_header") else None
        return self._request("POST", self.endpoint, payload, extra)

    def get_task(self, task_id: str) -> Any:
        normalized = validate_task_id(task_id)
        return self._request("GET", f"{self.endpoint}/{quote(normalized, safe='')}")

    def list_tasks(self, page_size: int = 20) -> Any:
        if not 1 <= page_size <= 100:
            raise ValidationError("page_size deve ficar entre 1 e 100")
        return self._request("GET", f"{self.endpoint}?{urlencode({'page_size': page_size})}")

    def download(self, url: str, destination: Path) -> dict[str, Any]:
        validate_official_asset_url(url, self.config["safety"]["allowed_asset_host_suffixes"], "video_url")
        if destination.exists():
            raise ValidationError("o clipe de destino já existe e não será sobrescrito")
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".partial")
        if partial.exists():
            raise ValidationError("já existe um download parcial; preserve e revise antes de tentar novamente")
        if self.download_transport:
            payload = self.download_transport(url)
            with partial.open("xb") as handle:
                handle.write(payload)
        else:
            request = urllib.request.Request(url, method="GET")
            try:
                opener = urllib.request.build_opener(_OfficialAssetRedirect(self.config["safety"]["allowed_asset_host_suffixes"]))
                with opener.open(request, timeout=max(self.timeout, 180.0)) as response, partial.open("xb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
                raise ArkNetworkError(f"download interrompido; parcial preservado: {redact_text(str(exc))}") from exc
        os.replace(partial, destination)
        return {"path": str(destination), "bytes": destination.stat().st_size, "sha256": sha256_file(destination)}


def _active_tasks(manifest: dict[str, Any]) -> list[str]:
    active = []
    for task_id, task in manifest.get("tasks", {}).items():
        status = str(task.get("status", "unknown")).lower()
        if status in _ACTIVE_STATES or (status in _SUCCESS_STATES and not task.get("local_file")):
            active.append(task_id)
    for key, entry in manifest.get("idempotency_keys", {}).items():
        if entry.get("status") in _ACTIVE_STATES and not entry.get("task_id"):
            active.append(key)
    for key, entry in manifest.get("image_idempotency_keys", {}).items():
        if entry.get("status") in {"submitting", "ambiguous"}:
            active.append(key)
    return sorted(set(active))


def submit_task(project: Project, shot: dict[str, Any], client: ArkClient, approved: bool) -> dict[str, Any]:
    from .approvals import validate_submission_gates  # evita ciclo de importação

    config = project.models_config()
    payload = build_payload(shot, config)
    gates = validate_submission_gates(project, shot, payload, approved)
    manifest = project.manifest()
    key = idempotency_key(manifest["project_id"], str(shot["id"]), payload)

    with exclusive_lock(project.root / "locks" / "paid-submission.lock"):
        manifest = project.manifest()
        if key in manifest.get("idempotency_keys", {}):
            raise DuplicateSubmissionError("este payload já foi reservado/enviado; recupere a tarefa, não reenvie")
        active = _active_tasks(manifest)
        if active:
            raise DuplicateSubmissionError(f"há operação paga ativa ou ambígua: {active[0]}")
        reservation = {
            "shot_id": shot["id"], "status": "submitting", "created_at": utc_now(),
            "payload_sha256": sha256_json(payload), "estimate_path": gates["estimate_path"],
            "approval_path": gates["approval_path"], "task_id": None,
        }

        def reserve(value: dict[str, Any]) -> None:
            value.setdefault("idempotency_keys", {})[key] = reservation

        project.update_manifest("paid_submission_reserved", reserve)
        write_versioned_json(project.root / "tasks" / "submissions", key, {
            "idempotency_key": key, "request": redact_data(payload), "reservation": reservation
        })
        task_id = None
        try:
            response = client.create_task(payload, key)
            task_id = response.get("id") or response.get("task_id") or response.get("data", {}).get("id")
            if not task_id:
                raise AmbiguousSubmissionError("a API respondeu sem task ID; reenvio proibido")
            task_id = validate_task_id(str(task_id))
            record = write_versioned_json(project.root / "tasks" / task_id, "submission", {
                "task_id": task_id, "shot_id": shot["id"], "idempotency_key": key,
                "request": redact_data(payload), "response": redact_data(response), "created_at": utc_now(),
            })

            def complete(value: dict[str, Any]) -> None:
                value["idempotency_keys"][key].update({"status": "submitted", "task_id": task_id, "updated_at": utc_now()})
                value.setdefault("tasks", {})[task_id] = {
                    "task_id": task_id, "shot_id": shot["id"], "idempotency_key": key,
                    "status": "submitted", "model": payload["model"], "created_at": utc_now(),
                    "submission_record": project.relative(record), "payload_sha256": sha256_json(payload),
                }

            project.update_manifest("paid_submission_accepted", complete)
            project.audit("paid_submission_accepted", {"shot_id": shot["id"], "task_id": task_id})
            return {"task_id": task_id, "idempotency_key": key, "response": redact_data(response)}
        except ArkHTTPError as exc:
            uncertain = exc.status in {408, 409, 425, 429} or exc.status >= 500
            outcome = "ambiguous" if uncertain else "rejected"

            def rejected(value: dict[str, Any]) -> None:
                value["idempotency_keys"][key].update({"status": outcome, "error": redact_data(exc.body), "http_status": exc.status, "updated_at": utc_now()})

            project.update_manifest("paid_submission_" + outcome, rejected)
            project.audit("paid_submission_" + outcome, {"shot_id": shot["id"], "http_status": exc.status})
            if uncertain:
                raise AmbiguousSubmissionError(
                    f"HTTP {exc.status} pode ter aceitado a tarefa; não reenvie. Consulte tasks existentes. Chave: {key}"
                ) from exc
            raise
        except Exception as exc:
            error_message = redact_text(str(exc))
            recovery_id = task_id or "desconhecido"

            def ambiguous(value: dict[str, Any]) -> None:
                entry = value["idempotency_keys"][key]
                entry.update({"status": "ambiguous", "error": error_message, "updated_at": utc_now()})
                if task_id:
                    entry["recovery_task_id"] = task_id

            try:
                project.update_manifest("paid_submission_ambiguous", ambiguous)
                project.audit("paid_submission_ambiguous", {"shot_id": shot["id"], "idempotency_key": key, "recovery_task_id": recovery_id})
            except Exception as persistence_error:
                raise AmbiguousSubmissionError(
                    f"resultado ambíguo e falha ao persistir estado; NÃO reenvie. Task ID de recuperação: {recovery_id}; "
                    f"chave: {key}; erro local: {redact_text(str(persistence_error))}"
                ) from exc
            raise AmbiguousSubmissionError(
                f"resultado ambíguo; não reenvie. Consulte tasks existentes e recupere pelo task ID. "
                f"Task ID de recuperação: {recovery_id}; chave: {key}"
            ) from exc


def _validate_task_association(
    manifest: dict[str, Any], task_id: str, explicit_key: str | None,
) -> None:
    entries = manifest.get("idempotency_keys", {})
    task = manifest.get("tasks", {}).get(task_id, {})
    candidates = []
    if explicit_key:
        selected = entries.get(explicit_key)
        if not selected:
            raise ValidationError("idempotency key não encontrada; associação não foi tentada")
        for field in ("task_id", "recovery_task_id"):
            if selected.get(field) and selected[field] != task_id:
                raise ValidationError(f"a idempotency key já está associada a outro task ID em {field}")
    for key, entry in entries.items():
        linked = entry.get("task_id") == task_id or entry.get("recovery_task_id") == task_id
        if explicit_key and key != explicit_key and linked:
            raise ValidationError("task ID já pertence a outra idempotency key; associação cruzada recusada")
        if not explicit_key and linked:
            candidates.append(key)
    owner = task.get("idempotency_key")
    if explicit_key:
        if owner and owner != explicit_key:
            raise ValidationError("task ID já tem outro proprietário no manifesto")
        if task.get("local_file") and owner != explicit_key:
            raise ValidationError("task ID já baixado por outra operação; associação recusada")
    else:
        if len(candidates) > 1:
            raise ValidationError("task ID possui múltiplas idempotency keys; reconciliação manual obrigatória")
        if owner and candidates and owner not in candidates:
            raise ValidationError("proprietário da tarefa diverge da idempotency key registrada")


def recover_task(
    project: Project, task_id: str, client: ArkClient, idempotency_key: str | None = None,
) -> dict[str, Any]:
    normalized = validate_task_id(task_id)
    _validate_task_association(project.manifest(), normalized, idempotency_key)
    response = client.get_task(normalized)
    status = str(response.get("status") or response.get("data", {}).get("status") or "unknown").lower()
    record = write_versioned_json(project.root / "tasks" / normalized, "status", {
        "task_id": normalized, "retrieved_at": utc_now(), "response": redact_data(response),
    })
    video_url = (
        response.get("content", {}).get("video_url") or response.get("video_url")
        or response.get("data", {}).get("content", {}).get("video_url")
    )

    def update(value: dict[str, Any]) -> None:
        _validate_task_association(value, normalized, idempotency_key)
        task = value.setdefault("tasks", {}).setdefault(normalized, {"task_id": normalized, "shot_id": None})
        task.update({"status": status, "last_checked_at": utc_now(), "latest_status_record": project.relative(record)})
        if video_url:
            task["video_url"] = video_url
        selected_keys = []
        for key, entry in value.get("idempotency_keys", {}).items():
            selected = key == idempotency_key if idempotency_key else (entry.get("task_id") == normalized or entry.get("recovery_task_id") == normalized)
            if selected:
                if entry.get("task_id") and entry["task_id"] != normalized:
                    raise ValidationError("conflito de associação entre idempotency key e task ID")
                entry["task_id"] = normalized
                entry["status"] = status
                entry["updated_at"] = utc_now()
                selected_keys.append(key)
                if not task.get("shot_id"):
                    task["shot_id"] = entry.get("shot_id")
        if selected_keys:
            task["idempotency_key"] = selected_keys[0]

    project.update_manifest("task_recovered", update)
    project.audit("task_recovered", {"task_id": normalized, "status": status, "explicit_idempotency_link": bool(idempotency_key)})
    return {"task_id": normalized, "status": status, "video_url": video_url, "response": response}


def list_task_candidates(project: Project, client: ArkClient, page_size: int = 20) -> dict[str, Any]:
    response = client.list_tasks(page_size)
    record = write_versioned_json(project.root / "tasks" / "lists", "tasks", {"retrieved_at": utc_now(), "response": redact_data(response)})
    project.audit("task_list_read", {"record": project.relative(record), "note": "nenhuma tarefa criada"})
    return redact_data(response)


def download_task(
    project: Project, task_id: str, client: ArkClient, idempotency_key: str | None = None,
) -> dict[str, Any]:
    normalized = validate_task_id(task_id)
    _validate_task_association(project.manifest(), normalized, idempotency_key)
    existing = project.manifest().get("tasks", {}).get(normalized, {})
    if existing.get("local_file"):
        path = project.resolve(existing["local_file"])
        if not path.is_file():
            raise ValidationError("o manifesto aponta para um clipe ausente; nenhuma cópia nova foi criada")
        digest = sha256_file(path)
        if existing.get("local_sha256") and digest != existing["local_sha256"]:
            raise ValidationError("o clipe local diverge do hash do manifesto; nenhuma cópia nova foi criada")
        return {
            "task_id": normalized, "shot_id": existing.get("shot_id"), "path": existing["local_file"],
            "bytes": path.stat().st_size, "sha256": digest, "kind": "original", "already_downloaded": True,
        }
    recovered = recover_task(project, normalized, client, idempotency_key)
    if recovered["status"] not in _SUCCESS_STATES:
        raise ValidationError(f"tarefa ainda não está pronta: {recovered['status']}")
    url = recovered.get("video_url")
    if not url:
        raise ValidationError("tarefa concluída sem video_url; nenhuma nova geração foi criada")
    manifest = project.manifest()
    task = manifest.get("tasks", {}).get(normalized, {})
    shot_id = task.get("shot_id") or "UNASSIGNED"
    destination = project.root / "clips" / "original" / shot_id / f"{normalized}-{timestamp_tag()}.mp4"
    downloaded = client.download(url, destination)
    relative = project.relative(destination)
    record = {
        "task_id": normalized, "shot_id": shot_id, "path": relative,
        "bytes": downloaded["bytes"], "sha256": downloaded["sha256"], "downloaded_at": utc_now(),
        "kind": "original", "preserved": True,
    }

    def update(value: dict[str, Any]) -> None:
        value["tasks"][normalized].update({
            "local_file": relative, "local_sha256": downloaded["sha256"],
            "bytes": downloaded["bytes"], "downloaded_at": record["downloaded_at"],
        })
        value.setdefault("clips", []).append(record)

    project.update_manifest("task_downloaded", update)
    project.audit("task_downloaded", {"task_id": normalized, "path": relative, "sha256": downloaded["sha256"]})
    return record
