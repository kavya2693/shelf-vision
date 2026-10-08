"""Deterministic planogram compliance. Detections in camera pixels are mapped back through the
camera homography to the bay plane, assigned to slots by geometry, and turned into a per-slot
status. A temporal tracker then requires a status to persist across consecutive unoccluded
frames before it is confirmed, so a shopper standing in front of a shelf is not an
out-of-stock alert. No language model is involved anywhere in this module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .catalog import FAMILY_BY_NAME, Sku
from .config import OCCLUDED_FRACTION, PERSIST_FRAMES
from .detector import Detection
from .planogram import Planogram, Slot
from .render import px_to_mm, unwarp_rect

STATUS_ORDER = ("ok", "missing_tag", "wrong_facings", "misplaced", "out_of_stock")
WEAK_EVIDENCE = 0.4  # confidence given to a finding that rests on an absence, not a detection


@dataclass
class SlotObservation:
    slot_id: str
    bay_id: str
    camera_id: str
    frame: int
    expected_sku: str
    expected_family: str
    expected_facings: int
    found_expected: int = 0
    found_foreign: int = 0
    foreign_family: str | None = None
    gap_fraction: float = 0.0
    tag_seen: bool = False
    occluded: float = 0.0
    confidence: float = 0.0
    raw_status: str = "ok"
    detections: list[int] = field(default_factory=list)  # indices into the frame's detection list

    @property
    def observed(self) -> bool:
        return self.occluded < OCCLUDED_FRACTION

    def to_dict(self) -> dict:
        return asdict(self)


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def _area(a: tuple[float, float, float, float]) -> float:
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])


def slot_region_mm(slot: Slot) -> tuple[float, float, float, float]:
    return float(slot.x0), float(slot.y1 - slot.pack_h), float(slot.x1), float(slot.y1)


def assign(det_mm: tuple[float, float, float, float], slots: list[Slot], tag: bool = False) -> Slot | None:
    """The slot whose region (or tag rail) a bay-plane rectangle overlaps most; None if the
    rectangle is mostly outside every slot."""
    best, best_ov = None, 0.0
    for s in slots:
        region = tuple(float(v) for v in s.tag_rect()) if tag else slot_region_mm(s)
        ov = _overlap(det_mm, region)  # type: ignore[arg-type]
        if ov > best_ov:
            best, best_ov = s, ov
    if best is None or best_ov < 0.3 * _area(det_mm):
        return None
    return best


def observe(
    plan: Planogram,
    catalog: dict[str, Sku],
    camera_id: str,
    frame: int,
    detections: list[Detection],
) -> list[SlotObservation]:
    """Map one frame's detections onto the camera's bay and derive each slot's raw status."""
    cam = plan.camera(camera_id)
    bay = plan.bay(cam.bay_id)
    h = np.array(cam.homography, dtype=np.float64)
    obs = {
        s.slot_id: SlotObservation(
            s.slot_id,
            bay.bay_id,
            camera_id,
            frame,
            s.sku,
            catalog[s.sku].short,
            s.facings,
        )
        for s in bay.slots
    }
    confs: dict[str, list[float]] = {k: [] for k in obs}
    gap_conf: dict[str, list[float]] = {k: [] for k in obs}
    shoppers = [d.xyxy for d in detections if d.cls == "shopper"]
    for i, d in enumerate(detections):
        if d.cls == "shopper":
            continue
        mm = px_to_mm(unwarp_rect(h, d.xyxy))
        slot = assign(mm, bay.slots, tag=d.cls == "price_tag")
        if slot is None:
            continue
        o = obs[slot.slot_id]
        o.detections.append(i)
        if d.cls == "price_tag":
            o.tag_seen = True
        elif d.cls == "gap":
            width = max(1.0, float(slot.x1 - slot.x0))
            o.gap_fraction = min(
                1.0, o.gap_fraction + _overlap(mm, slot_region_mm(slot)) / (width * slot.pack_h)
            )
            gap_conf[slot.slot_id].append(d.conf)
        elif d.cls == o.expected_family:
            o.found_expected += 1
            confs[slot.slot_id].append(d.conf)
        else:
            o.found_foreign += 1
            o.foreign_family = d.cls
            confs[slot.slot_id].append(d.conf)
    # Occlusion from the shopper boxes the detector itself found, in image pixels.
    from .render import slot_image_rect

    for s in bay.slots:
        region = slot_image_rect(s, h)
        area = _area(region)
        covered = sum(_overlap(region, sb) for sb in shoppers)
        obs[s.slot_id].occluded = min(1.0, covered / area) if area > 0 else 0.0
    for s in bay.slots:
        o = obs[s.slot_id]
        o.raw_status, o.confidence = _status(o, confs[s.slot_id], gap_conf[s.slot_id])
    return [obs[s.slot_id] for s in bay.slots]


def _status(o: SlotObservation, confs: list[float], gap_conf: list[float]) -> tuple[str, float]:
    mean = float(np.mean(confs)) if confs else 0.0
    gap = float(np.mean(gap_conf)) if gap_conf else 0.0
    if o.found_expected == 0 and o.found_foreign == 0:
        # Nothing where stock should be. A detected gap is strong evidence; silence is weak.
        return "out_of_stock", gap if gap_conf else WEAK_EVIDENCE
    if o.found_foreign > 0:
        return "misplaced", mean
    if o.found_expected < o.expected_facings:
        return "wrong_facings", max(gap, WEAK_EVIDENCE) if gap_conf else WEAK_EVIDENCE
    if not o.tag_seen:
        return "missing_tag", min(mean, 0.7)
    return "ok", mean


# ── Temporal smoothing ───────────────────────────────────────────────────────
@dataclass
class TrackState:
    confirmed: str = "ok"
    candidate: str = "ok"
    streak: int = 0
    confidence: float = 0.0
    confirmed_frame: int = -1
    last_observed_frame: int = -1


class SlotTracker:
    """A status change is confirmed only after `persist` consecutive observed frames agree.
    Frames where the slot is hidden behind a shopper are skipped: they neither advance nor
    reset the streak, because they carry no information about the shelf."""

    def __init__(self, persist: int = PERSIST_FRAMES, state: dict | None = None):
        self.persist = persist
        self.state: dict[str, TrackState] = {k: TrackState(**v) for k, v in (state or {}).items()}

    def update(self, o: SlotObservation) -> TrackState:
        st = self.state.setdefault(o.slot_id, TrackState())
        if not o.observed:
            return st
        st.last_observed_frame = o.frame
        if o.raw_status == st.candidate:
            st.streak += 1
        else:
            st.candidate, st.streak = o.raw_status, 1
        st.confidence = o.confidence
        if st.candidate != st.confirmed and st.streak >= self.persist:
            st.confirmed, st.confirmed_frame = st.candidate, o.frame
        return st

    def status(self, slot_id: str) -> str:
        return self.state[slot_id].confirmed if slot_id in self.state else "ok"

    def to_dict(self) -> dict:
        return {k: asdict(v) for k, v in self.state.items()}


# ── Metrics ──────────────────────────────────────────────────────────────────
def compliance_metrics(statuses: dict[str, str], plan: Planogram | None = None) -> dict:
    """Planogram compliance is the share of slots exactly as planned; on-shelf availability is
    the share where the planned product is present at all (a short-faced or untagged slot still
    sells; an empty or wrongly filled one does not)."""
    n = max(1, len(statuses))
    counts = {s: 0 for s in STATUS_ORDER}
    for v in statuses.values():
        counts[v] = counts.get(v, 0) + 1
    out = {
        "slots": len(statuses),
        "compliance": round(counts["ok"] / n, 3),
        "osa": round(1 - (counts["out_of_stock"] + counts["misplaced"]) / n, 3),
        "gaps": counts["out_of_stock"],
        "by_status": counts,
    }
    if plan is not None:
        bays = {}
        for b in plan.bays:
            ids = [s.slot_id for s in b.slots if s.slot_id in statuses]
            if ids:
                ok = sum(statuses[i] == "ok" for i in ids)
                avail = sum(statuses[i] not in ("out_of_stock", "misplaced") for i in ids)
                bays[b.bay_id] = {"compliance": round(ok / len(ids), 3), "osa": round(avail / len(ids), 3)}
        out["by_bay"] = bays
    return out


def family_velocity(sku: Sku) -> float:
    return FAMILY_BY_NAME[sku.family].velocity
