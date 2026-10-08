import numpy as np

from shelf_vision.catalog import CLASS_NAMES, build_catalog
from shelf_vision.data import TRAIN_RATES, fault_state, ok_state, random_states
from shelf_vision.planogram import build_planogram, random_bay
from shelf_vision.render import (
    FrameSpec,
    Lighting,
    camera_homography,
    coverage,
    random_occluders,
    render_frame,
    unwarp_rect,
    warp_rect,
    yolo_label,
)


def _frame(seed: int):
    catalog = build_catalog()
    by = {s.sku: s for s in catalog}
    rng = np.random.default_rng(seed)
    bay = random_bay("T0", catalog, rng)
    spec = FrameSpec(
        random_states(bay, catalog, rng, TRAIN_RATES), random_occluders(rng, 2), Lighting.random(rng)
    )
    return render_frame(bay, spec, by, camera_homography(rng), rng)


def test_catalog_and_planogram_are_deterministic():
    a, b = build_catalog(), build_catalog()
    assert [s.to_dict() for s in a] == [s.to_dict() for s in b]
    assert {s.family for s in a} == {f for f in {s.family for s in a}} and len(a) == 45
    pa, pb = build_planogram(a), build_planogram(b)
    assert pa.to_dict() == pb.to_dict()
    assert len(pa.slots) == 90 and len(pa.cameras) == 6


def test_rendering_is_deterministic_and_labels_are_valid():
    img1, boxes1 = _frame(11)
    img2, boxes2 = _frame(11)
    assert np.array_equal(np.asarray(img1), np.asarray(img2))
    assert [b.to_dict() for b in boxes1] == [b.to_dict() for b in boxes2]
    img3, _ = _frame(12)
    assert not np.array_equal(np.asarray(img1), np.asarray(img3))
    for row in yolo_label(boxes1).splitlines():
        cls, cx, cy, w, h = row.split()
        assert 0 <= int(cls) < len(CLASS_NAMES)
        assert all(0 <= float(v) <= 1 for v in (cx, cy, w, h))


def test_fault_states_map_to_the_expected_status():
    catalog = build_catalog()
    plan = build_planogram(catalog)
    rng = np.random.default_rng(0)
    slot = next(s for s in plan.slots if s.facings >= 2)
    assert ok_state(slot).status(slot.sku) == "ok"
    for fault in TRAIN_RATES:
        assert fault_state(slot, fault, catalog, rng).status(slot.sku) == fault
    single = next(s for s in plan.slots if s.facings == 1)
    # A one-facing slot cannot be short-faced: the fault degrades to out of stock.
    assert fault_state(single, "wrong_facings", catalog, rng).status(single.sku) == "out_of_stock"


def test_homography_round_trips_and_occluders_hide_labels():
    rng = np.random.default_rng(3)
    h = camera_homography(rng)
    rect = (100.0, 50.0, 180.0, 120.0)
    back = unwarp_rect(h, warp_rect(h, rect))
    # Bounding a warped box and unwarping it again can only grow it, and only by a few pixels.
    assert back[0] <= rect[0] and back[1] <= rect[1] and back[2] >= rect[2] and back[3] >= rect[3]
    assert np.allclose(back, rect, atol=6)
    catalog = build_catalog()
    by = {s.sku: s for s in catalog}
    bay = random_bay("T1", catalog, rng)
    states = {s.slot_id: ok_state(s) for s in bay.slots}
    _, clear = render_frame(bay, FrameSpec(states, [], Lighting()), by, h, np.random.default_rng(1))
    occ = random_occluders(np.random.default_rng(2), 3)
    _, hidden = render_frame(bay, FrameSpec(states, occ, Lighting()), by, h, np.random.default_rng(1))
    products = lambda boxes: [b for b in boxes if b.cls not in ("shopper",)]  # noqa: E731
    assert len(products(hidden)) < len(products(clear))
    assert sum(b.cls == "shopper" for b in hidden) == 3
    assert all(coverage(b, occ) <= 0.65 for b in products(hidden))
