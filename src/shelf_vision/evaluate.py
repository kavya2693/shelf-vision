"""Measures the compliance pipeline against the ground truth of the deployment sequences:
per-slot status accuracy, false alerts (an alert on a slot that is actually fine), misses,
and time-to-detect (frames from a fault appearing to the first alert), each with temporal
smoothing on and off. The two headline numbers pull in opposite directions: smoothing buys
fewer false alerts with slower detection."""

from __future__ import annotations

import json

from .catalog import Sku
from .compliance import STATUS_ORDER, SlotTracker, observe
from .config import METRICS, N_FRAMES, OCCLUDED_FRACTION, PERSIST_FRAMES
from .data import load_truth
from .detector import Detection, Detector
from .pipeline import default_detector, frame_path
from .planogram import Planogram, load_catalog, load_planogram


def predict_statuses(
    plan: Planogram, catalog: dict[str, Sku], detector: Detector, persist: int
) -> dict[str, dict[int, dict[str, str]]]:
    """camera -> frame -> slot -> confirmed status, with one tracker per camera."""
    out: dict[str, dict[int, dict[str, str]]] = {}
    for cam in plan.cameras:
        tracker = SlotTracker(persist)
        out[cam.camera_id] = {}
        for t in range(N_FRAMES):
            dets = detector.detect(frame_path(cam.camera_id, t))
            if persist == 1:  # raw: every frame speaks, occluded or not
                obs = observe(plan, catalog, cam.camera_id, t, dets)
                out[cam.camera_id][t] = {o.slot_id: o.raw_status for o in obs}
                continue
            for o in observe(plan, catalog, cam.camera_id, t, dets):
                tracker.update(o)
            out[cam.camera_id][t] = {s.slot_id: tracker.status(s.slot_id) for s in plan.bay(cam.bay_id).slots}
    return out


def score(pred: dict, truth: dict) -> dict:
    total = correct = 0
    ok_frames = false_alerts = 0
    occluded_ok = occluded_false = 0
    fault_frames = misses = 0
    confusion = {a: {b: 0 for b in STATUS_ORDER} for a in STATUS_ORDER}
    ttd, undetected = [], 0
    for cam, cv in truth["cameras"].items():
        for fr in cv["frames"]:
            t = fr["t"]
            for slot_id, gt in fr["slots"].items():
                p = pred[cam][t][slot_id]
                g = gt["status"]
                total += 1
                correct += p == g
                confusion[g][p] += 1
                if g == "ok":
                    ok_frames += 1
                    false_alerts += p != "ok"
                    if gt["occluded"] >= OCCLUDED_FRACTION:
                        occluded_ok += 1
                        occluded_false += p != "ok"
                else:
                    fault_frames += 1
                    misses += p == "ok"
        for ev in cv["events"]:
            onset = ev["frame"]
            first = next((t for t in range(onset, N_FRAMES) if pred[cam][t][ev["slot_id"]] != "ok"), None)
            if first is None:
                undetected += 1
            else:
                ttd.append(first - onset)
    return {
        "slot_frames": total,
        "status_accuracy": round(correct / max(total, 1), 3),
        "false_alert_rate": round(false_alerts / max(ok_frames, 1), 4),
        "false_alerts": false_alerts,
        "false_alert_rate_when_occluded": round(occluded_false / max(occluded_ok, 1), 3),
        "occluded_ok_slot_frames": occluded_ok,
        "miss_rate": round(misses / max(fault_frames, 1), 3),
        "events": len(ttd) + undetected,
        "events_detected": len(ttd),
        "mean_time_to_detect": round(sum(ttd) / len(ttd), 2) if ttd else None,
        "confusion": confusion,
    }


def evaluate_pipeline(detector: Detector | None = None, persist: int = PERSIST_FRAMES) -> dict:
    plan = load_planogram()
    catalog = {s.sku: s for s in load_catalog()}
    truth = load_truth()
    detector = detector or default_detector()
    raw = score(predict_statuses(plan, catalog, detector, 1), truth)
    smoothed = score(predict_statuses(plan, catalog, detector, persist), truth)
    out = {"detector": detector.name, "persist_frames": persist, "raw": raw, "smoothed": smoothed}
    METRICS.mkdir(parents=True, exist_ok=True)
    (METRICS / "pipeline.json").write_text(json.dumps(out, indent=1))
    return out


def detections_of(cache: dict, cam: str, t: int) -> list[Detection]:
    return [Detection.from_dict(d) for d in cache["frames"][cam][str(t)]]
