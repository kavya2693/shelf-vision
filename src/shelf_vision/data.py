"""Seeded synthetic data: the catalogue, the store planogram, a training set of random bays
for the detector, and the deployment sequences (one short frame sequence per camera) the
twin steps through, with per-frame ground truth for every slot. No real store data is used."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

from .catalog import CLASS_NAMES, Sku, build_catalog
from .config import (
    DATA,
    N_FRAMES,
    SEED,
    TEST_IMAGES,
    TRAIN_IMAGES,
    VAL_IMAGES,
)
from .planogram import (
    Bay,
    Planogram,
    Slot,
    build_planogram,
    random_bay,
    save_catalog,
    save_planogram,
)
from .render import (
    Box,
    FrameSpec,
    Lighting,
    SlotState,
    camera_homography,
    coverage,
    random_occluders,
    render_frame,
    slot_image_rect,
    yolo_label,
)

YOLO = DATA / "yolo"
SEQ = DATA / "sequence"

# Per-slot fault probabilities for random training bays.
TRAIN_RATES = {"out_of_stock": 0.10, "misplaced": 0.08, "wrong_facings": 0.10, "missing_tag": 0.08}


def ok_state(slot: Slot) -> SlotState:
    return SlotState([slot.sku] * slot.facings, True)


def fault_state(slot: Slot, fault: str, catalog: list[Sku], rng: np.random.Generator) -> SlotState:
    st = ok_state(slot)
    if fault == "out_of_stock":
        st.facings = [None] * slot.facings
    elif fault == "misplaced":
        # A foreign pack from another family pushed into the slot, usually at one facing.
        foreign = [s for s in catalog if s.family != catalog_by(catalog, slot.sku).family]
        st.facings[int(rng.integers(slot.facings))] = foreign[int(rng.integers(len(foreign)))].sku
    elif fault == "wrong_facings":
        if slot.facings == 1:
            return fault_state(slot, "out_of_stock", catalog, rng)
        missing = int(rng.integers(1, slot.facings))
        for j in rng.choice(slot.facings, size=missing, replace=False):
            st.facings[int(j)] = None
    elif fault == "missing_tag":
        st.tag = False
    return st


def catalog_by(catalog: list[Sku], sku: str) -> Sku:
    for s in catalog:
        if s.sku == sku:
            return s
    raise KeyError(sku)


def random_states(bay: Bay, catalog: list[Sku], rng: np.random.Generator, rates: dict[str, float]) -> dict:
    out = {}
    for slot in bay.slots:
        u = rng.random()
        acc = 0.0
        chosen = None
        for fault, p in rates.items():
            acc += p
            if u < acc:
                chosen = fault
                break
        out[slot.slot_id] = fault_state(slot, chosen, catalog, rng) if chosen else ok_state(slot)
    return out


# ── Training set ─────────────────────────────────────────────────────────────
def generate_training_set(catalog: list[Sku], seed: int = SEED) -> dict[str, int]:
    """Random bays, random faults, random cameras, random shoppers. Split by image index so a
    re-run reproduces the same split byte for byte."""
    rng = np.random.default_rng(seed + 100)
    by_id = {s.sku: s for s in catalog}
    if YOLO.exists():
        shutil.rmtree(YOLO)
    counts = {}
    splits = (("train", TRAIN_IMAGES), ("val", VAL_IMAGES), ("test", TEST_IMAGES))
    for split, n in splits:
        (YOLO / "images" / split).mkdir(parents=True)
        (YOLO / "labels" / split).mkdir(parents=True)
        for i in range(n):
            bay = random_bay(f"T{i:04d}", catalog, rng)
            states = random_states(bay, catalog, rng, TRAIN_RATES)
            occ = random_occluders(rng, int(rng.integers(0, 3))) if rng.random() < 0.55 else []
            spec = FrameSpec(states, occ, Lighting.random(rng))
            img, boxes = render_frame(bay, spec, by_id, camera_homography(rng), rng)
            img.save(YOLO / "images" / split / f"{split}_{i:04d}.png")
            (YOLO / "labels" / split / f"{split}_{i:04d}.txt").write_text(yolo_label(boxes))
        counts[split] = n
    (YOLO / "data.yaml").write_text(
        "\n".join(
            [
                f"path: {YOLO}",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                f"nc: {len(CLASS_NAMES)}",
                "names: [" + ", ".join(CLASS_NAMES) + "]",
                "",
            ]
        )
    )
    return counts


# ── Deployment sequences ─────────────────────────────────────────────────────
def generate_sequences(planogram: Planogram, catalog: list[Sku], seed: int = SEED) -> dict:
    """One sequence per camera. Faults are injected at scheduled frames and persist (nobody fixes
    the shelf until a task is done); shoppers pass through for one or two frames at a time.
    Returns the ground truth: per camera, per frame, per slot status, plus every box."""
    rng = np.random.default_rng(seed + 200)
    by_id = {s.sku: s for s in catalog}
    if SEQ.exists():
        shutil.rmtree(SEQ)
    truth: dict = {"frames": N_FRAMES, "cameras": {}}
    for cam in planogram.cameras:
        bay = planogram.bay(cam.bay_id)
        h = camera_homography(rng)
        cam.homography = h.tolist()
        states = {s.slot_id: ok_state(s) for s in bay.slots}
        # A couple of faults already present when the sequence starts.
        for slot in bay.slots:
            if rng.random() < 0.06:
                fault = str(rng.choice(list(TRAIN_RATES)))
                states[slot.slot_id] = fault_state(slot, fault, catalog, rng)
        # New faults appear at scheduled frames on slots that are still fine.
        healthy = [s for s in bay.slots if states[s.slot_id].status(s.sku) == "ok"]
        n_events = int(rng.integers(3, 6))
        events = []
        for slot in rng.choice(healthy, size=min(n_events, len(healthy)), replace=False):
            frame = int(rng.integers(1, N_FRAMES - 4))
            fault = str(rng.choice(list(TRAIN_RATES)))
            events.append((frame, slot, fault))
        # Shopper passes: short, so a transient occlusion must not raise an alert.
        passes: dict[int, list] = {}
        for _ in range(int(rng.integers(2, 5))):
            start = int(rng.integers(0, N_FRAMES - 1))
            occ = random_occluders(rng, int(rng.integers(1, 3)))
            for t in range(start, min(N_FRAMES, start + int(rng.integers(1, 3)))):
                passes.setdefault(t, []).extend(occ)
        base = Lighting.random(rng)
        base.blur = float(rng.choice([0.0, 0.6, 1.0]))
        cam_dir = SEQ / cam.camera_id
        cam_dir.mkdir(parents=True)
        frames = []
        for t in range(N_FRAMES):
            for frame, slot, fault in events:
                if frame == t:
                    states[slot.slot_id] = fault_state(slot, fault, catalog, rng)
            occ = passes.get(t, [])
            light = Lighting(
                brightness=float(np.clip(base.brightness + rng.normal(0, 0.04), 0.55, 1.3)),
                warmth=base.warmth,
                blur=base.blur,
                noise=base.noise,
                vignette=base.vignette,
            )
            spec = FrameSpec({k: SlotState(list(v.facings), v.tag) for k, v in states.items()}, occ, light)
            img, boxes = render_frame(bay, spec, by_id, h, rng)
            img.save(cam_dir / f"frame_{t:02d}.png")
            slots = {}
            for slot in bay.slots:
                st = states[slot.slot_id]
                r = slot_image_rect(slot, h)
                occluded = coverage(Box("slot", *r), occ)
                slots[slot.slot_id] = {
                    "status": st.status(slot.sku),
                    "facings": st.facings,
                    "tag": st.tag,
                    "occluded": round(occluded, 3),
                }
            frames.append({"t": t, "slots": slots, "boxes": [b.to_dict() for b in boxes], "shoppers": len(occ)})
        truth["cameras"][cam.camera_id] = {
            "bay_id": bay.bay_id,
            "events": [{"frame": f, "slot_id": s.slot_id, "fault": ft} for f, s, ft in events],
            "frames": frames,
        }
    (SEQ / "ground_truth.json").write_text(json.dumps(truth))
    return truth


def generate(seed: int = SEED, training: bool = True) -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    catalog = build_catalog(seed)
    save_catalog(catalog)
    plan = build_planogram(catalog, seed)
    counts = generate_training_set(catalog, seed) if training else {}
    truth = generate_sequences(plan, catalog, seed)
    save_planogram(plan)  # after sequences, so camera homographies are recorded
    return {"skus": len(catalog), "slots": len(plan.slots), "cameras": len(plan.cameras), **counts}


def load_truth(path: Path = SEQ / "ground_truth.json") -> dict:
    return json.loads(path.read_text())
