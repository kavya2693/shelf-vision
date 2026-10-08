"""The store digital twin: a clock over the camera frame sequences. Each step runs the agent
graph on the next frame for every camera, carries the slot tracker forward, keeps every task,
replenishment request and audit entry, and answers trace questions (camera, slot, task) for
the 3D front end. Pending human reviews are real LangGraph interrupts; a reviewer's decision
resumes the paused graph."""

from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from langgraph.types import Command
from PIL import Image, ImageDraw

from .catalog import FAMILY_BY_SHORT, Sku
from .compliance import compliance_metrics
from .config import METRICS, N_FRAMES, OUT, REVIEW_CONFIDENCE
from .data import SEQ, load_truth
from .detector import Detector, load_detector_metrics
from .graph import build_graph
from .pipeline import default_detector, frame_path
from .planogram import Planogram, load_catalog, load_planogram
from .render import mm_to_px, slot_image_rect, warp_rect
from .tasks import Task, check_inventory

BOX_COLOURS = {"gap": (239, 75, 75), "price_tag": (59, 130, 246), "shopper": (160, 160, 170)}


class Twin:
    def __init__(self, detector: Detector | None = None, interactive: bool = True, smoothing: bool = True):
        self.plan: Planogram = load_planogram()
        self.catalog: dict[str, Sku] = {s.sku: s for s in load_catalog()}
        self.detector = detector or default_detector()
        self.truth = load_truth() if (SEQ / "ground_truth.json").exists() else None
        self.graph = build_graph(self.plan, self.catalog, self.detector)
        self.interactive = interactive
        self.smoothing = smoothing
        self.frame = -1
        self.tracker: dict = {}
        self.stock = {s.sku: {"backroom": s.backroom, "dc": s.dc} for s in self.catalog.values()}
        self.tasks: dict[str, dict] = {}
        self.pending: list[dict] = []
        self.requests: list[dict] = []
        self.audit: list[dict] = []
        self.statuses: dict[str, str] = {s.slot_id: "ok" for s in self.plan.slots}
        self.confidences: dict[str, float] = {}
        self.observations: dict[int, dict[str, dict]] = {}  # frame -> slot_id -> observation
        self.detections: dict[int, dict[str, list[dict]]] = {}  # frame -> camera -> boxes
        self.history: list[dict] = []  # per-frame compliance metrics
        self.briefing = ""
        self.next_task = 1
        self.next_request = 1
        self._open_cfg: dict | None = None
        self._absorbed = 0

    # ── Clock ────────────────────────────────────────────────────────────────
    @property
    def done(self) -> bool:
        return self.frame >= N_FRAMES - 1

    def step(self) -> dict:
        if self.done:
            return {"frame": self.frame, "done": True}
        self._close_queue()
        self.frame += 1
        cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
        self._absorbed = 0
        state = self.graph.invoke(
            {
                "frame": self.frame,
                "interactive": self.interactive,
                "smoothing": self.smoothing,
                "tracker": self.tracker,
                "open_slots": sorted({t["slot_id"] for t in self.tasks.values()}),
                "stock": self.stock,
                "next_task": self.next_task,
                "next_request": self.next_request,
            },
            cfg,
        )
        self._absorb(state, cfg)
        return {"frame": self.frame, "done": self.done, "pending": len(self.pending)}

    def _close_queue(self) -> None:
        """Undecided reviews stay pending across frames; the graph itself must finish."""
        if self._open_cfg is not None:
            state = self.graph.invoke(Command(resume={"__close__": True}), self._open_cfg)
            self._absorb(state, self._open_cfg)

    def _absorb(self, state: dict, cfg: dict) -> None:
        audit = state.get("audit", [])
        self.audit.extend(audit[self._absorbed :])
        self._absorbed = len(audit)
        if "__interrupt__" in state:
            self._open_cfg = cfg
            self.pending = list(state["__interrupt__"][0].value["pending"])
            return
        self._open_cfg = None
        self.pending = []
        self.tracker = state.get("tracker_out", self.tracker)
        self.statuses.update(state.get("statuses", {}))
        self.confidences.update(state.get("confidences", {}))
        self.observations[self.frame] = {o["slot_id"]: o for o in state.get("observations", [])}
        self.detections[self.frame] = state.get("detections", {})
        for t in state.get("tasks", []):
            self.tasks[t["task_id"]] = t
            self.next_task = max(self.next_task, int(t["task_id"].split("-")[1]) + 1)
        for r in state.get("replenishment", []):
            self.requests.append(r)
            self.next_request = max(self.next_request, int(r["po_id"].split("-")[1]) + 1)
        self.stock = state.get("stock_out", self.stock)
        self.history.append({"frame": self.frame, **state.get("compliance", {})})
        self.briefing = state.get("briefing", "")

    # ── Human review ─────────────────────────────────────────────────────────
    def decide(self, task_id: str, approve: bool) -> dict:
        waiting = next((p for p in self.pending if p["task_id"] == task_id), None)
        if self._open_cfg is not None and waiting is not None:
            state = self.graph.invoke(Command(resume={task_id: approve}), self._open_cfg)
            self._absorb(state, self._open_cfg)
            # The graph may pause again for the next pending task; the decided one is then
            # not in the task table yet, so answer from the review record.
            return self.tasks.get(task_id) or {
                **waiting,
                "review": "approved" if approve else "rejected",
                "state": "issued" if approve else "rejected",
            }
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        if task["state"] != "pending_review":
            raise ValueError(f"{task_id} is already {task['state']}")
        # The graph that raised it has moved on; apply the decision directly and log it the same way.
        task["review"] = "approved" if approve else "rejected"
        task["state"] = "issued" if approve else "rejected"
        self.audit.append(
            {
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                "agent": "human_reviewer",
                "action": "decide",
                "frame": self.frame,
                "task": task_id,
                "slot": task["slot_id"],
                "sku": task["sku"],
                "camera": task["camera_id"],
                "approved": approve,
            }
        )
        if approve and task["type"] == "restock":
            tasks, requests, self.stock = check_inventory(
                [Task(**task)], self.catalog, self.stock, self.next_request
            )
            self.tasks[task_id] = tasks[0].to_dict()
            for r in requests:
                self.requests.append(r)
                self.next_request += 1
                self.audit.append(
                    {
                        **self.audit[-1],
                        "agent": "inventory_agent",
                        "action": "raise_replenishment",
                        "request": r["po_id"],
                    }
                )
        return self.tasks[task_id]

    # ── Views ────────────────────────────────────────────────────────────────
    def all_tasks(self) -> list[dict]:
        rows = list(self.tasks.values())
        known = {t["task_id"] for t in rows}
        for p in self.pending:  # raised by the paused graph, not yet in the task table
            if p["task_id"] not in known:
                rows.append(
                    {
                        **p,
                        "state": "pending_review",
                        "review": "pending",
                        "frame": self.frame,
                        "priority": 0,
                        "qty": 0,
                        "bay_id": self.plan.slot(p["slot_id"]).bay_id,
                        "family": self.catalog[p["sku"]].family,
                        "source": None,
                        "request_id": None,
                    }
                )
        return sorted(
            rows, key=lambda t: (t["state"] != "pending_review", -float(t.get("priority", 0)), t["task_id"])
        )

    def kpis(self) -> dict:
        tasks = self.all_tasks()
        by_type: dict[str, int] = {}
        by_state: dict[str, int] = {}
        for t in tasks:
            by_type[t["type"]] = by_type.get(t["type"], 0) + 1
            by_state[t["state"]] = by_state.get(t["state"], 0) + 1
        m = compliance_metrics(self.statuses, self.plan) if self.frame >= 0 else compliance_metrics({})
        det = load_detector_metrics()
        pipe = (
            json.loads((METRICS / "pipeline.json").read_text())
            if (METRICS / "pipeline.json").exists()
            else {}
        )
        return {
            **m,
            "frame": self.frame,
            "frames": N_FRAMES,
            "tasks_total": len(tasks),
            "tasks_by_type": by_type,
            "tasks_by_state": by_state,
            "pending_reviews": by_state.get("pending_review", 0),
            "replenishment_requests": len(self.requests),
            "replenishment_value": round(sum(r["value"] for r in self.requests), 2),
            "detector": self.detector.name,
            "map50": det.get("map50"),
            "map50_95": det.get("map50_95"),
            "train_seconds": det.get("train_seconds"),
            "false_alert_rate": pipe.get("smoothed", {}).get("false_alert_rate"),
            "false_alert_rate_raw": pipe.get("raw", {}).get("false_alert_rate"),
            "time_to_detect": pipe.get("smoothed", {}).get("mean_time_to_detect"),
            "time_to_detect_raw": pipe.get("raw", {}).get("mean_time_to_detect"),
            "status_accuracy": pipe.get("smoothed", {}).get("status_accuracy"),
        }

    def snapshot(self, events: int = 120) -> dict:
        slots = []
        for s in self.plan.slots:
            sku = self.catalog[s.sku]
            task = next(
                (t for t in self.all_tasks() if t["slot_id"] == s.slot_id and t["state"] != "rejected"), None
            )
            slots.append(
                {
                    "slot_id": s.slot_id,
                    "bay_id": s.bay_id,
                    "shelf": s.shelf,
                    "index": s.index,
                    "sku": s.sku,
                    "family": sku.family,
                    "short": sku.short,
                    "rgb": list(sku.rgb),
                    "facings": s.facings,
                    "status": self.statuses.get(s.slot_id, "ok"),
                    "confidence": self.confidences.get(s.slot_id),
                    "task_id": task["task_id"] if task else None,
                    "task_state": task["state"] if task else None,
                }
            )
        cams = []
        for c in self.plan.cameras:
            boxes = self.detections.get(self.frame, {}).get(c.camera_id, [])
            cams.append(
                {
                    "camera_id": c.camera_id,
                    "bay_id": c.bay_id,
                    "label": c.label,
                    "boxes": len(boxes),
                    "shoppers": sum(1 for b in boxes if b["cls"] == "shopper"),
                    "frame_url": f"/api/frame/{c.camera_id}/{max(self.frame, 0)}.png",
                }
            )
        return {
            "store": self.plan.store,
            "frame": self.frame,
            "frames": N_FRAMES,
            "done": self.done,
            "detector": self.detector.name,
            "bays": [
                {
                    "bay_id": b.bay_id,
                    "aisle": b.aisle,
                    "side": b.side,
                    "families": b.families,
                    "camera_id": b.camera_id,
                }
                for b in self.plan.bays
            ],
            "cameras": cams,
            "slots": slots,
            "tasks": self.all_tasks(),
            "pending": self.pending,
            "requests": self.requests,
            "stock": self.stock,
            "kpis": self.kpis(),
            "history": self.history,
            "audit": self.audit[-events:],
            "briefing": self.briefing,
        }

    # ── Traces ───────────────────────────────────────────────────────────────
    def trace_camera(self, camera_id: str) -> dict:
        cam = self.plan.camera(camera_id)
        bay = self.plan.bay(cam.bay_id)
        t = max(self.frame, 0)
        boxes = self.detections.get(t, {}).get(camera_id, [])
        statuses = {s.slot_id: self.statuses.get(s.slot_id, "ok") for s in bay.slots}
        return {
            "camera": {"camera_id": cam.camera_id, "bay_id": cam.bay_id, "label": cam.label},
            "bay": {"bay_id": bay.bay_id, "aisle": bay.aisle, "side": bay.side, "families": bay.families},
            "frame": t,
            "frame_url": f"/api/frame/{camera_id}/{t}.png",
            "detections": boxes,
            "by_class": _count(b["cls"] for b in boxes),
            "slots": [
                {"slot_id": k, "status": v, "confidence": self.confidences.get(k)}
                for k, v in statuses.items()
            ],
            "compliance": compliance_metrics(statuses),
            "tasks": [x for x in self.all_tasks() if x["camera_id"] == camera_id],
            "audit": [a for a in self.audit if a.get("camera") == camera_id][-40:],
            "events": (self.truth or {}).get("cameras", {}).get(camera_id, {}).get("events", []),
        }

    def trace_slot(self, slot_id: str) -> dict:
        s = self.plan.slot(slot_id)
        sku = self.catalog[s.sku]
        cam = self.plan.bay(s.bay_id).camera_id
        t = max(self.frame, 0)
        obs = self.observations.get(t, {}).get(slot_id)
        timeline = [
            {
                "frame": f,
                "raw": o[slot_id]["raw_status"],
                "confidence": o[slot_id]["confidence"],
                "occluded": o[slot_id]["occluded"],
            }
            for f, o in sorted(self.observations.items())
            if slot_id in o
        ]
        dets = self.detections.get(t, {}).get(cam, [])
        truth = None
        if self.truth and self.frame >= 0:
            truth = self.truth["cameras"][cam]["frames"][t]["slots"].get(slot_id, {}).get("status")
        tasks = [x for x in self.all_tasks() if x["slot_id"] == slot_id]
        return {
            "slot": {
                "slot_id": s.slot_id,
                "bay_id": s.bay_id,
                "shelf": s.shelf,
                "index": s.index,
                "camera_id": cam,
            },
            "planogram": {
                "sku": sku.sku,
                "family": sku.family,
                "facings": s.facings,
                "price": sku.price,
                "tag": True,
            },
            "detected": None
            if obs is None
            else {
                "facings_found": obs["found_expected"],
                "foreign": obs["found_foreign"],
                "foreign_family": FAMILY_BY_SHORT[obs["foreign_family"]].name
                if obs.get("foreign_family")
                else None,
                "gap_fraction": obs["gap_fraction"],
                "tag_seen": obs["tag_seen"],
                "occluded": obs["occluded"],
                "raw_status": obs["raw_status"],
                "confidence": obs["confidence"],
            },
            "status": self.statuses.get(slot_id, "ok"),
            "confidence": self.confidences.get(slot_id),
            "tracker": self.tracker.get(slot_id),
            "review_threshold": REVIEW_CONFIDENCE,
            "truth": truth,
            "frame": t,
            "frame_url": f"/api/frame/{cam}/{t}.png?slot={slot_id}",
            "detections": [dets[i] for i in (obs["detections"] if obs else []) if i < len(dets)],
            "timeline": timeline,
            "tasks": tasks,
            "requests": [r for r in self.requests if r["slot_id"] == slot_id],
            "stock": self.stock.get(sku.sku),
            "velocity": sku.velocity,
            "audit": [a for a in self.audit if a.get("slot") == slot_id][-30:],
        }

    def trace_task(self, task_id: str) -> dict:
        task = next((x for x in self.all_tasks() if x["task_id"] == task_id), None)
        if task is None:
            raise KeyError(task_id)
        slot = self.trace_slot(task["slot_id"])
        return {
            "task": task,
            "slot": slot["slot"],
            "planogram": slot["planogram"],
            "detected": slot["detected"],
            "status": slot["status"],
            "stock": slot["stock"],
            "frame_url": f"/api/frame/{task['camera_id']}/{task['frame']}.png?slot={task['slot_id']}",
            "request": next((r for r in self.requests if r.get("task_id") == task_id), None),
            "audit": [a for a in self.audit if a.get("task") == task_id or a.get("slot") == task["slot_id"]][
                -30:
            ],
            "steps": _task_steps(task, self.audit),
        }

    def frame_png(self, camera_id: str, t: int, slot_id: str | None = None, boxes: bool = True) -> bytes:
        img = Image.open(frame_path(camera_id, t)).convert("RGB")
        d = ImageDraw.Draw(img)
        cam = self.plan.camera(camera_id)
        h = np.array(cam.homography)
        if boxes:
            for b in self.detections.get(t, {}).get(camera_id, []):
                col = BOX_COLOURS.get(b["cls"], (57, 193, 122))
                x0, y0, x1, y1 = b["xyxy"]
                d.rectangle([x0, y0, x1, y1], outline=col, width=2)
                d.text((x0 + 2, y0 + 1), f"{b['cls']} {b['conf']:.2f}", fill=col)
        if slot_id:
            s = self.plan.slot(slot_id)
            r = slot_image_rect(s, h)
            d.rectangle([r[0] - 3, r[1] - 3, r[2] + 3, r[3] + 3], outline=(255, 122, 26), width=3)
            tr = warp_rect(h, mm_to_px(s.tag_rect()))
            d.rectangle([tr[0] - 2, tr[1] - 2, tr[2] + 2, tr[3] + 2], outline=(255, 122, 26), width=1)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def _count(items) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def _task_steps(task: dict, audit: list[dict]) -> list[dict]:
    """The journey of one task for the trace panel: detected, matched, proposed, reviewed, stocked."""
    tid, slot = task["task_id"], task["slot_id"]
    cam = task["camera_id"]
    seen = any(
        a["agent"] == "vision_agent" and a.get("camera") == cam and a.get("frame") == task["frame"]
        for a in audit
    )
    matched = any(
        a["agent"] == "compliance_agent" and a.get("camera") == cam and a.get("frame") == task["frame"]
        for a in audit
    )
    proposed = any(a.get("task") == tid and a["agent"] == "merchandising_agent" for a in audit)
    reviewed = task["review"] in ("approved", "rejected")
    needs_review = task["review"] != "auto"
    stocked = task.get("source") is not None
    steps = [
        {"name": "Frame detected", "done": seen, "detail": f"{cam} frame {task['frame']}"},
        {"name": "Planogram matched", "done": matched, "detail": f"{slot}: {task['finding']}"},
        {
            "name": "Task proposed",
            "done": proposed,
            "detail": f"{task['type']} priority {task.get('priority', 0)}",
        },
        {
            "name": "Human review",
            "done": reviewed or not needs_review,
            "detail": "not needed" if not needs_review else task["review"],
        },
    ]
    if task["type"] == "restock":
        steps.append({"name": "Stock checked", "done": stocked, "detail": task.get("source") or "waiting"})
    return steps


# ── One-command run ──────────────────────────────────────────────────────────
def run_all(interactive: bool = False, detector: Detector | None = None) -> str:
    twin = Twin(detector=detector, interactive=interactive)
    while not twin.done:
        twin.step()
        while twin.pending and interactive:
            pending = list(twin.pending)
            print(f"\nframe {twin.frame}: {len(pending)} findings need a reviewer")
            for p in pending:
                label = f"{p['task_id']} {p['slot_id']} {p['finding']:14} conf {p['confidence']:.2f}"
                a = input(f"  {label}  approve? [y/N] ")
                twin.decide(p["task_id"], a.strip().lower() == "y")
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = pd.DataFrame(twin.all_tasks())
    tasks.to_csv(OUT / "tasks.csv", index=False)
    pd.DataFrame(twin.requests).to_csv(OUT / "replenishment_requests.csv", index=False)
    pd.DataFrame(twin.snapshot()["slots"]).to_csv(OUT / "slot_status.csv", index=False)
    pd.DataFrame(twin.history).to_csv(OUT / "compliance_history.csv", index=False)
    with open(OUT / "audit_log.jsonl", "w") as f:
        for row in twin.audit:
            f.write(json.dumps(row, default=str) + "\n")
    report = _report(twin)
    (OUT / "run_report.md").write_text(report)
    return report


def _report(twin: Twin) -> str:
    k = twin.kpis()
    lines = [
        "# Shelf run report",
        "",
        f"**Detector:** {k['detector']}"
        + (
            f", test mAP50 {k['map50']:.3f} (mAP50-95 {k['map50_95']:.3f}), "
            f"trained in {k['train_seconds']} s on CPU"
            if k.get("map50")
            else ""
        ),
        "",
        f"**After frame {k['frame'] + 1} of {k['frames']}:** planogram compliance {k['compliance']:.1%}, "
        f"on-shelf availability {k['osa']:.1%}, {k['gaps']} empty slots of {k['slots']}.",
        "",
        "**Slot status:** " + ", ".join(f"{s}: {n}" for s, n in k["by_status"].items()),
        "",
        "**Tasks:** "
        + ", ".join(f"{s}: {n}" for s, n in sorted(k["tasks_by_type"].items()))
        + " · "
        + ", ".join(f"{s}: {n}" for s, n in sorted(k["tasks_by_state"].items())),
        "",
        f"**Replenishment requests:** {k['replenishment_requests']} (value {k['replenishment_value']:,.2f})",
    ]
    if k.get("false_alert_rate") is not None:
        lines += [
            "",
            f"**Smoothing:** false-alert rate {k['false_alert_rate_raw']:.1%} raw -> "
            f"{k['false_alert_rate']:.1%} smoothed; "
            f"mean time-to-detect {k['time_to_detect_raw']:.1f} -> {k['time_to_detect']:.1f} frames.",
        ]
    lines += ["", "**Briefing:**", twin.briefing, ""]
    return "\n".join(lines)


def plain(obj: Any) -> Any:
    """numpy and pandas scalars to plain JSON."""
    return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
