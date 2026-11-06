from __future__ import annotations

import json
import os
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from studio.approvals import record_approval, record_frame_review
from studio.costs import save_estimate
from studio.project import new_project, read_json, sha256_file, write_text_new

REPO_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_FIRST = "https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_image/r2v_tea_pic1.jpg"
OFFICIAL_LAST = "https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_image/r2v_tea_pic2.jpg"


def write_json_fixture(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_png(path: Path, width: int, height: int, rgb=(32, 64, 96)) -> Path:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgb) * width
    payload = zlib.compress(row * height, level=9)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += chunk(b"IDAT", payload) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def known_price(entry: dict, key: str, value: str) -> None:
    entry.update({
        key: value, "currency": "USD", "effective_date": "2026-11-01",
        "retrieved_at": "2026-11-06T00:00:00Z", "source_url": "https://docs.byteplus.com/en/docs/modelark/model-pricing",
    })


class OfflineStudioTest(unittest.TestCase):
    def setUp(self) -> None:
        temp_base = REPO_ROOT / "tests" / ".tmp"
        temp_base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="studio-offline-", dir=temp_base)
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        for name in ("models.example.json", "pricing.example.json"):
            shutil.copyfile(REPO_ROOT / "config" / name, self.root / "config" / name)
        self.network_patch = patch("urllib.request.urlopen", side_effect=AssertionError("rede proibida nos testes offline"))
        self.network_patch.start()

    def tearDown(self) -> None:
        self.network_patch.stop()
        self.temporary.cleanup()

    def make_project(self, name="demo"):
        return new_project(self.root, name)

    def prepare_shot(self, project, paid_config=True, known_pricing=True):
        shot_id = "SHOT-001"
        make_png(project.root / "frames" / shot_id / "first.png", 1280, 720)
        make_png(project.root / "frames" / shot_id / "last.png", 1280, 720, (48, 80, 112))

        def update(shot):
            shot.update({
                "prompt": "A single ceramic cup rests on a wooden table; the camera slowly pushes in; no text.",
                "image_costs_reconciled": True,
                "frames": {
                    **shot["frames"], "first_url": OFFICIAL_FIRST, "last_url": OFFICIAL_LAST,
                    "first_file": f"frames/{shot_id}/first.png", "last_file": f"frames/{shot_id}/last.png",
                },
            })
        shot = project.update_shot(shot_id, "offline_fixture", update)
        pricing = project.pricing_config()
        if known_pricing:
            known_price(pricing["video_models"][shot["model"]]["resolutions"]["720p"], "price_per_second", "0.20")
            known_price(pricing["image_models"]["gpt-image-2.5-flare"]["qualities"]["low"], "price_per_image", "0.04")
            known_price(pricing["image_models"]["gpt-image-2.5-sunburst"]["qualities"]["low"], "price_per_image", "0.08")
        write_json_fixture(project.root / "config" / "pricing.json", pricing)
        models = project.models_config()
        if paid_config:
            models["safety"]["allow_paid_submissions"] = True
            models["models"][shot["model"]]["availability"] = "verified_available"
            models["models"][shot["model"]]["enabled_for_submission"] = True
        write_json_fixture(project.root / "config" / "models.json", models)
        write_text_new(project.root / "reviews" / "frames" / "independent-report.md", "Parecer sintético de teste: APROVADO\n")
        return shot

    def approve_ready(self, project, shot=None):
        if not (project.root / "reviews" / "frames" / "independent-report.md").is_file():
            self.prepare_shot(project)
        shot = shot or project.shot("SHOT-001")
        review_path, review = record_frame_review(project, shot, "Revisor Independente de Teste", "approved", "reviews/frames/independent-report.md")
        estimate_path, estimate = save_estimate(project, shot)
        approval_path, approval = record_approval(
            project, shot, "Usuário Sintético de Teste", f"APROVO {sha256_file(estimate_path)}"
        )
        return {
            "shot": shot, "review_path": review_path, "review": review,
            "estimate_path": estimate_path, "estimate": estimate,
            "approval_path": approval_path, "approval": approval,
        }
