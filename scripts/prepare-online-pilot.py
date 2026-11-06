from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

from studio.costs import save_estimate
from studio.frames import compare_frame_dimensions
from studio.project import Project, read_json, timestamp_tag, write_bytes_new, write_json_new

project = Project.open(Path.cwd(), "studio-selfcheck")
now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
first_path = project.root / "frames" / "SHOT-001" / "first-v2-16x9.jpg"
last_path = project.root / "frames" / "SHOT-001" / "last-v2-16x9.jpg"
comparison = compare_frame_dimensions(first_path, last_path, "16:9")
if not comparison["ok"]:
    raise RuntimeError(comparison["errors"])
first_data = "data:image/jpeg;base64," + base64.b64encode(first_path.read_bytes()).decode("ascii")
last_data = "data:image/jpeg;base64," + base64.b64encode(last_path.read_bytes()).decode("ascii")
prompt = (
    "First-person POV fruit tea promotional ad, using Image 1 as the exact opening frame and Image 2 as the exact final frame. "
    "Keep the camera locked and keep the thin black letterbox bars unchanged. "
    "0–1.5 seconds: the hand simply holds a dew-covered red apple steady. "
    "At 1.5 seconds, use a hard match cut, not a morph: the apple is no longer visible and the same first-person hand now holds a finished layered fruit tea with milk foam, prepared off-screen. "
    "1.5–4 seconds: the hand moves the cup forward toward the lens in a toast; the camera does not move. "
    "4–5 seconds: the hand and cup stop completely on Image 2. "
    "Preserve the same hand, setting, cup design, and the pink front sticker reading \"Seedance\" in its existing position. "
    "No additional people, no objects materializing, no added captions, no new logos, no watermark, no music, and no voice."
)
shot = project.update_shot("SHOT-001", "online_pilot_frames_and_prompt", lambda value: value.update({
    "status": "ready_for_human_frame_review",
    "prompt": prompt,
    "frames": {
        **value["frames"],
        "first_url": first_data,
        "last_url": last_data,
        "first_file": "frames/SHOT-001/first-v2-16x9.jpg",
        "last_file": "frames/SHOT-001/last-v2-16x9.jpg",
    },
    "image_calls": [],
    "image_costs_reconciled": True,
    "notes": "Frames oficiais de exemplo preservados em v1; versões v2 têm padding local para 1280×720. Prompt baseado na descrição fornecida pelo usuário, sem inspeção visual pelo agente.",
}))

models = project.models_config()
account = read_json(project.root / "reports" / "account-models.json")
tag = timestamp_tag()
write_bytes_new(project.root / "history" / "config" / f"models-{tag}.json", (project.root / "config" / "models.json").read_bytes())
write_bytes_new(project.root / "history" / "config" / f"pricing-{tag}.json", (project.root / "config" / "pricing.json").read_bytes())
models["account_discovery"] = {
    "status": "verified_in_models_api",
    "checked_at": now,
    "available_model_ids": [item["id"] for item in account["matches"]],
    "note": "GET /api/v3/models retornou 200; nenhuma tarefa foi criada.",
}
mini = models["models"]["dreamina-seedance-2-0-mini-260615"]
mini.update({
    "availability": "verified_available",
    "enabled_for_submission": True,
    "supported_durations": [5],
    "supported_resolutions": ["720p"],
})
models["safety"]["allow_paid_submissions"] = False
(project.root / "config" / "models.json").write_text(json.dumps(models, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

pricing = project.pricing_config()
entry = pricing["video_models"]["dreamina-seedance-2-0-mini-260615"]["resolutions"]["720p"]
entry.update({
    "price_per_second": "0.08",
    "currency": "USD",
    "effective_date": "2026-10-23",
    "retrieved_at": now,
    "source_url": "https://docs.byteplus.com/en/docs/modelark/model-pricing",
    "notes": "Tabela renderizada: Resolution=720p, Mini=$0.08/second e $0.38/video para 5s. Estimativa conservadora por segundo: 5×$0.08=$0.40.",
})
pricing["retrieved_at"] = now
pricing["source"]["note"] = "Preço confirmado na tabela oficial renderizada; não foram usados preços do guia ou de terceiros."
(project.root / "config" / "pricing.json").write_text(json.dumps(pricing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
write_json_new(project.root / "reports" / f"pricing-evidence-{tag}.json", {
    "source_url": "https://docs.byteplus.com/en/docs/modelark/model-pricing",
    "retrieved_at": now,
    "table": ["Resolution", "480p", "720p", "1080p", "4K"],
    "mini_row": ["Dreamina Seedance 2.0 Mini", "$0.18 per video / $0.04 per second", "$0.38 per video / $0.08 per second", "Not supported", "Not supported"],
    "selected": {"resolution": "720p", "duration_seconds": 5, "price_per_second": "0.08", "currency": "USD", "conservative_total": "0.40"},
})
estimate_path, estimate = save_estimate(project, shot)
print(f"ESTIMATE_PATH={project.relative(estimate_path)}")
print(f"TOTAL={estimate['total_amount']} {estimate['currency']}")
print(f"PAID_SUBMISSIONS_ENABLED={models['safety']['allow_paid_submissions']}")
