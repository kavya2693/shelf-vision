"""Glue between the data on disk and the detectors: frame paths, the detection cache written
by `shelf-vision detect`, and the detector the twin should use."""

from __future__ import annotations

import json
from pathlib import Path

from .config import DATA, N_FRAMES
from .data import SEQ, load_truth
from .detector import WEIGHTS, CachedDetector, Detector, OracleDetector, YoloDetector
from .planogram import Planogram, load_planogram

DETECTIONS = DATA / "detections.json"


def frame_path(camera_id: str, t: int) -> Path:
    return SEQ / camera_id / f"frame_{t:02d}.png"


def cache_detections(oracle: bool = False, plan: Planogram | None = None) -> dict:
    plan = plan or load_planogram()
    det: Detector = OracleDetector(load_truth()) if oracle else YoloDetector(WEIGHTS)
    frames: dict[str, dict[str, list[dict]]] = {}
    n = 0
    for cam in plan.cameras:
        frames[cam.camera_id] = {}
        for t in range(N_FRAMES):
            boxes = det.detect(frame_path(cam.camera_id, t))
            frames[cam.camera_id][str(t)] = [b.to_dict() for b in boxes]
            n += len(boxes)
    DETECTIONS.write_text(json.dumps({"detector": det.name, "frames": frames}))
    return {"detector": det.name, "frames": len(plan.cameras) * N_FRAMES, "detections": n}


def default_detector() -> Detector:
    """Cached model detections when they exist, otherwise the ground-truth oracle (and the
    twin says so in its snapshot)."""
    if DETECTIONS.exists():
        return CachedDetector(DETECTIONS)
    return OracleDetector(load_truth())
