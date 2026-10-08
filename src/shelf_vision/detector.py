"""The object detector. A YOLOv8n fine-tuned on the synthetic set, CPU only, plus an oracle
that replays ground-truth boxes so the downstream pipeline can be tested without weights.

Classes are the nine product families, the empty-facing region, the price tag and the
shopper. Family-level rather than SKU-level: at CCTV resolution the thing a camera can tell
apart reliably is colour and pack shape, which is family; which SKU belongs at a slot is
already known from the planogram, so SKU identity is resolved by slot geometry, not by the
network. The cost is that a swap between two SKUs of the same family is invisible."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .catalog import CLASS_NAMES
from .config import CONF_THRESHOLD, EPOCHS, IMGSZ, METRICS, MODELS, SEED

WEIGHTS = MODELS / "shelf_vision.pt"
PRETRAINED = MODELS / "yolov8n.pt"
DATA_YAML = MODELS.parent / "yolo" / "data.yaml"


@dataclass
class Detection:
    cls: str
    conf: float
    xyxy: tuple[float, float, float, float]

    def to_dict(self) -> dict:
        return {"cls": self.cls, "conf": round(self.conf, 3), "xyxy": [round(v, 1) for v in self.xyxy]}

    @classmethod
    def from_dict(cls, d: dict) -> Detection:
        return cls(d["cls"], float(d["conf"]), tuple(float(v) for v in d["xyxy"]))  # type: ignore[arg-type]


class Detector(Protocol):
    name: str

    def detect(self, image: Path) -> list[Detection]: ...


class YoloDetector:
    name = "yolov8n"

    def __init__(self, weights: Path = WEIGHTS, conf: float = CONF_THRESHOLD):
        from ultralytics import YOLO

        if not weights.exists():
            raise FileNotFoundError(f"{weights} not found; run `shelf-vision train` first")
        self.model = YOLO(str(weights))
        self.conf = conf

    def detect(self, image: Path) -> list[Detection]:
        res = self.model.predict(str(image), imgsz=IMGSZ, conf=self.conf, device="cpu", verbose=False)[0]
        out = []
        for b in res.boxes:
            cls = CLASS_NAMES[int(b.cls.item())]
            x0, y0, x1, y1 = (float(v) for v in b.xyxy[0].tolist())
            out.append(Detection(cls, float(b.conf.item()), (x0, y0, x1, y1)))
        return out


class OracleDetector:
    """Replays ground-truth boxes with a fixed confidence: the upper bound on what the
    pipeline can do, and the detector the tests use."""

    name = "oracle"

    def __init__(self, truth: dict, conf: float = 0.9):
        self.truth = truth
        self.conf = conf

    def detect(self, image: Path) -> list[Detection]:
        cam, t = image.parent.name, int(image.stem.split("_")[1])
        frame = self.truth["cameras"][cam]["frames"][t]
        return [Detection(b["cls"], self.conf, tuple(b["xyxy"])) for b in frame["boxes"]]


class CachedDetector:
    """Serves detections written by `shelf-vision detect`, so the API and the twin never
    load torch."""

    name = "cached"

    def __init__(self, path: Path):
        self.cache = json.loads(path.read_text())
        self.name = self.cache.get("detector", "cached")

    def detect(self, image: Path) -> list[Detection]:
        cam, t = image.parent.name, image.stem.split("_")[1]
        return [Detection.from_dict(d) for d in self.cache["frames"][cam][t]]


def train(epochs: int = EPOCHS, imgsz: int = IMGSZ, data_yaml: Path = DATA_YAML) -> dict[str, Any]:
    """Fine-tune YOLOv8n on CPU and evaluate on the held-out test split. Writes the weights and
    an honest metrics file (including per-class AP, so the weak classes are visible)."""
    from ultralytics import YOLO

    t0 = time.time()
    model = YOLO(str(PRETRAINED))
    run_dir = MODELS.parent.parent / "runs"
    model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=16,
        device="cpu",
        workers=2,
        seed=SEED,
        deterministic=True,
        project=str(run_dir),
        name="shelf_vision",
        exist_ok=True,
        verbose=False,
        plots=False,
        # The renderer already varies lighting, blur, noise and perspective; flips would
        # teach the model mirrored price tags and upside-down bottles.
        fliplr=0.0,
        mosaic=0.5,
        hsv_h=0.01,
        hsv_s=0.3,
        hsv_v=0.3,
        close_mosaic=2,
    )
    train_seconds = time.time() - t0
    best = run_dir / "shelf_vision" / "weights" / "best.pt"
    MODELS.mkdir(parents=True, exist_ok=True)
    shutil.copy(best, WEIGHTS)
    metrics = evaluate(WEIGHTS, imgsz, data_yaml)
    metrics |= {"epochs": epochs, "imgsz": imgsz, "train_seconds": round(train_seconds), "device": "cpu"}
    METRICS.mkdir(parents=True, exist_ok=True)
    (METRICS / "detector.json").write_text(json.dumps(metrics, indent=1))
    return metrics


def evaluate(weights: Path = WEIGHTS, imgsz: int = IMGSZ, data_yaml: Path = DATA_YAML, split: str = "test") -> dict:
    from ultralytics import YOLO

    model = YOLO(str(weights))
    res = model.val(data=str(data_yaml), split=split, imgsz=imgsz, device="cpu", verbose=False, plots=False)
    per_class = {}
    for i, idx in enumerate(res.box.ap_class_index):
        per_class[CLASS_NAMES[int(idx)]] = {
            "ap50": round(float(res.box.ap50[i]), 3),
            "ap50_95": round(float(res.box.ap[i]), 3),
        }
    return {
        "split": split,
        "map50": round(float(res.box.map50), 3),
        "map50_95": round(float(res.box.map), 3),
        "precision": round(float(np.mean(res.box.p)), 3),
        "recall": round(float(np.mean(res.box.r)), 3),
        "per_class": per_class,
    }


def load_detector_metrics() -> dict:
    p = METRICS / "detector.json"
    return json.loads(p.read_text()) if p.exists() else {}
