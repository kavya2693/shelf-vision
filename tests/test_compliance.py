from shelf_vision.compliance import SlotObservation, SlotTracker, compliance_metrics, observe
from shelf_vision.config import N_FRAMES, OCCLUDED_FRACTION
from shelf_vision.detector import OracleDetector
from shelf_vision.pipeline import frame_path


def test_slot_mapping_recovers_ground_truth_on_unoccluded_slots(dataset):
    plan, catalog, truth = dataset
    oracle = OracleDetector(truth)
    checked = agree = 0
    for cam in plan.cameras:
        for t in range(N_FRAMES):
            gt = truth["cameras"][cam.camera_id]["frames"][t]["slots"]
            for o in observe(plan, catalog, cam.camera_id, t, oracle.detect(frame_path(cam.camera_id, t))):
                if gt[o.slot_id]["occluded"] >= OCCLUDED_FRACTION:
                    continue  # hidden behind a shopper: the detector cannot see it either
                checked += 1
                agree += o.raw_status == gt[o.slot_id]["status"]
    assert checked > 1000
    # Geometry alone maps ground-truth boxes to the right slot and status almost every time;
    # the residue is packs partly hidden by a shopper whose box was still kept as visible.
    assert agree / checked >= 0.97, f"{agree}/{checked}"


def test_compliance_metrics_math():
    statuses = {
        "a": "ok",
        "b": "ok",
        "c": "out_of_stock",
        "d": "misplaced",
        "e": "wrong_facings",
        "f": "missing_tag",
        "g": "ok",
        "h": "ok",
        "i": "ok",
        "j": "out_of_stock",
    }
    m = compliance_metrics(statuses)
    assert m["slots"] == 10
    assert m["compliance"] == 0.5  # 5 of 10 exactly as planned
    assert m["osa"] == 0.7  # 3 of 10 have no sellable product: 2 empty, 1 foreign
    assert m["gaps"] == 2
    assert m["by_status"]["missing_tag"] == 1
    assert compliance_metrics({})["compliance"] == 0.0


def _obs(frame: int, status: str, occluded: float = 0.0, conf: float = 0.9) -> SlotObservation:
    return SlotObservation(
        "S", "B", "C", frame, "RTL-0000", "produce", 2, raw_status=status, occluded=occluded, confidence=conf
    )


def test_smoothing_suppresses_transient_occlusion_but_confirms_persistent_faults():
    tracker = SlotTracker(persist=3)
    tracker.update(_obs(0, "ok"))
    # A shopper hides the slot for two frames; the raw status says empty because nothing is seen.
    tracker.update(_obs(1, "out_of_stock", occluded=0.9))
    tracker.update(_obs(2, "out_of_stock", occluded=0.8))
    assert tracker.status("S") == "ok"
    tracker.update(_obs(3, "ok"))
    assert tracker.status("S") == "ok"
    # Without smoothing the same frames are alerts.
    raw = SlotTracker(persist=1)
    raw.update(_obs(1, "out_of_stock", occluded=0.0))
    assert raw.status("S") == "out_of_stock"
    # A real gap persists and is confirmed on the third consistent frame, not before.
    tracker.update(_obs(4, "out_of_stock"))
    tracker.update(_obs(5, "out_of_stock"))
    assert tracker.status("S") == "ok"
    tracker.update(_obs(6, "out_of_stock"))
    assert tracker.status("S") == "out_of_stock"
    assert tracker.state["S"].confirmed_frame == 6
    # A single contradicting frame resets the streak.
    tracker.update(_obs(7, "ok"))
    tracker.update(_obs(8, "ok"))
    assert tracker.status("S") == "out_of_stock"
    tracker.update(_obs(9, "ok"))
    assert tracker.status("S") == "ok"
    # Tracker state survives a round trip through plain dicts (it is carried in graph state).
    again = SlotTracker(persist=3, state=tracker.to_dict())
    assert again.status("S") == "ok" and again.state["S"].streak == 3
