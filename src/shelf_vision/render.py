"""Renders CCTV-style shelf frames from a bay planogram and a per-slot state: product packs
as shaped, coloured, labelled blocks; empty facings showing the shelf back; price tags on
the rail; a fixed per-camera perspective; lighting drift, blur and sensor noise; shoppers
and trolleys occluding parts of the shelf. Every box the detector is trained on comes out
of the same code that drew the pixels, so ground truth is known by construction."""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .catalog import CLASS_ID, Sku
from .config import BAY_WIDTH_MM, IMG_H, IMG_W, SHELF_BOARD_MM, SHELF_PITCH_MM, SHELVES_PER_BAY
from .planogram import BAY_HEIGHT_MM, Bay, Slot

MARGIN = 18
STATUSES = ("ok", "out_of_stock", "misplaced", "wrong_facings", "missing_tag")


@dataclass
class SlotState:
    """What is physically on one slot: one entry per planned facing (the expected SKU, a foreign
    SKU, or None for an empty facing) and whether the price tag is on the rail."""

    facings: list[str | None]
    tag: bool = True

    def status(self, expected: str) -> str:
        if all(f is None for f in self.facings):
            return "out_of_stock"
        if any(f is not None and f != expected for f in self.facings):
            return "misplaced"
        if any(f is None for f in self.facings):
            return "wrong_facings"
        if not self.tag:
            return "missing_tag"
        return "ok"

    def to_dict(self) -> dict:
        return {"facings": self.facings, "tag": self.tag}

    @classmethod
    def from_dict(cls, d: dict) -> SlotState:
        return cls(list(d["facings"]), bool(d["tag"]))


@dataclass
class Box:
    cls: str
    x0: float
    y0: float
    x1: float
    y1: float
    slot_id: str | None = None
    sku: str | None = None

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)

    def to_dict(self) -> dict:
        return {
            "cls": self.cls,
            "xyxy": [round(self.x0, 1), round(self.y0, 1), round(self.x1, 1), round(self.y1, 1)],
            "slot_id": self.slot_id,
            "sku": self.sku,
        }


@dataclass
class Occluder:
    kind: str  # shopper | trolley
    x0: int
    y0: int
    x1: int
    y1: int
    rgb: tuple[int, int, int] = (60, 60, 70)


@dataclass
class Lighting:
    brightness: float = 1.0
    warmth: float = 0.0  # +ve warm (more red), -ve cool (more blue)
    blur: float = 0.0
    noise: float = 3.0
    vignette: float = 0.2

    @classmethod
    def random(cls, rng: np.random.Generator) -> Lighting:
        return cls(
            brightness=float(rng.uniform(0.65, 1.25)),
            warmth=float(rng.uniform(-0.08, 0.08)),
            blur=float(rng.choice([0.0, 0.0, 0.6, 1.0, 1.4])),
            noise=float(rng.uniform(2, 10)),
            vignette=float(rng.uniform(0.05, 0.4)),
        )


@dataclass
class FrameSpec:
    states: dict[str, SlotState]
    occluders: list[Occluder] = field(default_factory=list)
    lighting: Lighting = field(default_factory=Lighting)


# ── Geometry ─────────────────────────────────────────────────────────────────
def frontal_scale() -> tuple[float, float, float]:
    """Pixels per mm and the bay's top-left offset in the frontal (unwarped) image."""
    s = min((IMG_W - 2 * MARGIN) / BAY_WIDTH_MM, (IMG_H - 2 * MARGIN) / BAY_HEIGHT_MM)
    ox = (IMG_W - BAY_WIDTH_MM * s) / 2
    oy = (IMG_H - BAY_HEIGHT_MM * s) / 2
    return s, ox, oy


def mm_to_px(rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    s, ox, oy = frontal_scale()
    return rect[0] * s + ox, rect[1] * s + oy, rect[2] * s + ox, rect[3] * s + oy


def px_to_mm(rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    s, ox, oy = frontal_scale()
    return (rect[0] - ox) / s, (rect[1] - oy) / s, (rect[2] - ox) / s, (rect[3] - oy) / s


def camera_homography(rng: np.random.Generator) -> np.ndarray:
    """A fixed perspective for one camera: mounted high at one end of the aisle, so the near
    edge of the bay is taller and the far edge shorter, with a bit of keystone from looking down."""
    w, h = IMG_W, IMG_H
    side = 1 if rng.random() < 0.5 else -1  # which end of the aisle the camera sits at
    depth = rng.uniform(0.05, 0.16)  # how much the far edge shrinks
    tilt = rng.uniform(0.02, 0.07)  # looking down: top edge narrower
    shift = rng.uniform(-0.03, 0.03)
    near_x, far_x = (0, 1) if side > 0 else (1, 0)
    xs = {near_x: 0.0, far_x: depth}
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    dst = np.array(
        [
            [w * (xs[0] + tilt + shift), h * (xs[0] * 0.9)],
            [w * (1 - xs[1] - tilt + shift), h * (xs[1] * 0.9)],
            [w * (1 - xs[1] + shift), h * (1 - xs[1] * 0.9)],
            [w * (xs[0] + shift), h * (1 - xs[0] * 0.9)],
        ],
        dtype=np.float32,
    )
    return np.asarray(cv2.getPerspectiveTransform(src, dst), dtype=np.float64)


def warp_rect(h: np.ndarray, rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = rect
    pts = np.array([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]], dtype=np.float64)
    out = np.asarray(cv2.perspectiveTransform(pts, h))[0]
    return float(out[:, 0].min()), float(out[:, 1].min()), float(out[:, 0].max()), float(out[:, 1].max())


def unwarp_rect(h: np.ndarray, rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return warp_rect(np.linalg.inv(h), rect)


# ── Drawing ──────────────────────────────────────────────────────────────────
def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for name in ("Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _shade(rgb: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return tuple(int(max(0, min(255, c * k))) for c in rgb)  # type: ignore[return-value]


def draw_pack(d: ImageDraw.ImageDraw, sku: Sku, rect: tuple[float, float, float, float]) -> None:
    x0, y0, x1, y1 = (round(v) for v in rect)
    w, h = x1 - x0, y1 - y0
    base, dark, light = sku.rgb, _shade(sku.rgb, 0.6), _shade(sku.rgb, 1.25)
    shape = sku.shape
    if shape == "bottle":
        neck = max(2, w // 3)
        d.rectangle([x0 + neck, y0, x1 - neck, y0 + h // 6], fill=dark, outline=dark)
        d.rounded_rectangle([x0, y0 + h // 6, x1, y1], radius=max(2, w // 4), fill=base, outline=dark)
        d.rectangle([x0 + 1, y0 + h // 2, x1 - 1, y0 + int(h * 0.78)], fill=light)
    elif shape == "jug":
        d.rounded_rectangle([x0, y0 + h // 8, x1, y1], radius=max(2, w // 5), fill=base, outline=dark)
        d.rectangle([x0 + w // 4, y0, x1 - w // 4, y0 + h // 8], fill=dark)
        d.rectangle([x1 - max(3, w // 4), y0 + h // 4, x1 - 1, y0 + h // 2], fill=dark)
        d.rectangle([x0 + 2, y0 + h // 2, x1 - 2, y0 + int(h * 0.8)], fill=light)
    elif shape == "bag":
        d.polygon([(x0 + w // 6, y0), (x1 - w // 6, y0), (x1, y0 + h // 5), (x0, y0 + h // 5)], fill=dark)
        d.rounded_rectangle([x0, y0 + h // 5, x1, y1], radius=max(2, w // 5), fill=base, outline=dark)
        d.ellipse([x0 + w // 4, y0 + h // 2, x1 - w // 4, y1 - h // 6], fill=light)
    elif shape == "tub":
        d.rectangle([x0 - 1, y0, x1 + 1, y0 + h // 5], fill=light, outline=dark)
        d.rectangle([x0, y0 + h // 5, x1, y1], fill=base, outline=dark)
        d.rectangle([x0 + 2, y0 + h // 2, x1 - 2, y1 - 2], fill=dark)
    elif shape == "tube":
        d.rectangle([x0 + w // 4, y0, x1 - w // 4, y0 + h // 7], fill=dark)
        d.rounded_rectangle([x0, y0 + h // 7, x1, y1], radius=max(2, w // 3), fill=base, outline=dark)
        d.rectangle([x0 + 1, y0 + int(h * 0.4), x1 - 1, y0 + int(h * 0.6)], fill=light)
    elif shape == "blister":
        d.rectangle([x0, y0, x1, y1], fill=light, outline=dark)
        d.rectangle([x0, y0, x1, y0 + h // 4], fill=base)
        d.rounded_rectangle([x0 + w // 5, y0 + h // 3, x1 - w // 5, y1 - h // 8], radius=3, fill=dark)
    elif shape == "carton":
        d.rectangle([x0, y0, x1, y1], fill=base, outline=dark)
        d.rectangle([x0, y0 + h // 3, x1, y0 + h // 2], fill=light)
        d.rectangle([x0, y1 - h // 6, x1, y1], fill=dark)
    else:  # box
        d.rectangle([x0, y0, x1, y1], fill=base, outline=dark)
        d.rectangle([x0 + 2, y0 + h // 4, x1 - 2, y0 + int(h * 0.55)], fill=light)
    # A small label so packs carry some text structure like real print.
    if w >= 14 and h >= 20:
        f = _font(max(6, min(9, w // 3)))
        d.text((x0 + 3, y0 + int(h * 0.62)), sku.sku[-4:], fill=dark, font=f)


def draw_tag(d: ImageDraw.ImageDraw, rect: tuple[float, float, float, float], price: float) -> None:
    x0, y0, x1, y1 = (round(v) for v in rect)
    d.rectangle([x0, y0, x1, y1], fill=(250, 250, 245), outline=(120, 120, 120))
    d.rectangle([x0, y0, x0 + 4, y1], fill=(230, 60, 60))
    d.text((x0 + 7, y0 + 1), f"{price:.2f}", fill=(20, 20, 20), font=_font(max(6, (y1 - y0) - 3)))


def render_frontal(
    bay: Bay, states: dict[str, SlotState], catalog: dict[str, Sku], rng: np.random.Generator
) -> tuple[Image.Image, list[Box]]:
    """Draw the bay face-on. Returns the image and every object box in frontal pixels."""
    wall = tuple(int(v) for v in rng.integers(205, 235, size=3))
    floor = tuple(int(v) for v in rng.integers(150, 185, size=3))
    back = tuple(int(v) for v in rng.integers(40, 75, size=3))
    img = Image.new("RGB", (IMG_W, IMG_H), wall)  # type: ignore[arg-type]
    d = ImageDraw.Draw(img)
    bx0, by0, bx1, by1 = mm_to_px((0, 0, BAY_WIDTH_MM, BAY_HEIGHT_MM))
    d.rectangle([0, by1, IMG_W, IMG_H], fill=floor)  # type: ignore[arg-type]
    d.rectangle([bx0 - 4, by0 - 4, bx1 + 4, by1 + 4], fill=(90, 90, 95))  # bay frame
    d.rectangle([bx0, by0, bx1, by1], fill=back)  # type: ignore[arg-type]
    boxes: list[Box] = []
    # Shelf boards with the tag rail.
    for sh in range(SHELVES_PER_BAY):
        y_top = (sh + 1) * SHELF_PITCH_MM - SHELF_BOARD_MM
        r = mm_to_px((0, y_top, BAY_WIDTH_MM, y_top + SHELF_BOARD_MM))
        d.rectangle([r[0], r[1], r[2], r[3]], fill=(175, 175, 180), outline=(120, 120, 125))
        d.rectangle([r[0], r[1] + 2, r[2], r[3] - 2], fill=(225, 225, 228))
    for slot in bay.slots:
        st = states[slot.slot_id]
        # Empty runs of facings become gap boxes: the detector learns "shelf back where stock should be".
        run_start: int | None = None
        for j, present in enumerate([*st.facings, "end"]):
            if present is None and run_start is None:
                run_start = j
            if present is not None and run_start is not None:
                fx0 = slot.facing_rect(run_start)[0]
                fx1 = slot.facing_rect(j - 1)[2]
                if j - run_start == len(st.facings):  # whole slot empty: gap spans the slot
                    fx0, fx1 = slot.x0 + 4, slot.x1 - 4
                boxes.append(Box("gap", *mm_to_px((fx0, slot.y1 - slot.pack_h, fx1, slot.y1)), slot.slot_id))
                run_start = None
        for j, present in enumerate(st.facings):
            if present is None:
                continue
            sku = catalog[present]
            fx0, _, _, fy1 = slot.facing_rect(j)
            rect = (fx0, fy1 - sku.pack_mm[1], fx0 + min(sku.pack_mm[0], slot.pack_w), fy1)
            px = mm_to_px(rect)
            draw_pack(d, sku, px)
            boxes.append(Box(sku.short, *px, slot.slot_id, sku.sku))
        if st.tag:
            px = mm_to_px(slot.tag_rect())
            draw_tag(d, px, catalog[slot.sku].price)
            boxes.append(Box("price_tag", *px, slot.slot_id, slot.sku))
    return img, boxes


def warp(img: Image.Image, boxes: list[Box], h: np.ndarray) -> tuple[Image.Image, list[Box]]:
    arr = cv2.warpPerspective(
        np.asarray(img), h, (IMG_W, IMG_H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )
    out = [Box(b.cls, *warp_rect(h, (b.x0, b.y0, b.x1, b.y1)), b.slot_id, b.sku) for b in boxes]
    return Image.fromarray(arr), out


def random_occluders(rng: np.random.Generator, n: int) -> list[Occluder]:
    out = []
    for _ in range(n):
        if rng.random() < 0.65:
            w = int(IMG_W * rng.uniform(0.11, 0.2))
            hh = int(IMG_H * rng.uniform(0.45, 0.8))
            x0 = int(rng.uniform(0, IMG_W - w))
            rgb = tuple(int(v) for v in rng.integers(25, 120, size=3))
            out.append(Occluder("shopper", x0, IMG_H - hh, x0 + w, IMG_H, rgb))  # type: ignore[arg-type]
        else:
            w = int(IMG_W * rng.uniform(0.2, 0.32))
            hh = int(IMG_H * rng.uniform(0.22, 0.34))
            x0 = int(rng.uniform(0, IMG_W - w))
            out.append(Occluder("trolley", x0, IMG_H - hh, x0 + w, IMG_H, (120, 125, 135)))
    return out


def draw_occluders(img: Image.Image, occluders: list[Occluder]) -> list[Box]:
    d = ImageDraw.Draw(img)
    boxes = []
    for o in occluders:
        if o.kind == "shopper":
            w = o.x1 - o.x0
            head = int(w * 0.55)
            d.rounded_rectangle([o.x0, o.y0 + head, o.x1, o.y1], radius=w // 3, fill=o.rgb)
            d.ellipse(
                [o.x0 + (w - head) // 2, o.y0, o.x0 + (w + head) // 2, o.y0 + head], fill=(190, 150, 120)
            )
            d.rectangle(
                [o.x0 + w // 3, o.y0 + int((o.y1 - o.y0) * 0.55), o.x1 - w // 3, o.y1],
                fill=_shade(o.rgb, 0.7),
            )
        else:
            d.rectangle([o.x0, o.y0, o.x1, o.y1 - 6], outline=(70, 70, 80), width=2, fill=o.rgb)
            for k in range(1, 6):
                x = o.x0 + (o.x1 - o.x0) * k // 6
                d.line([x, o.y0, x, o.y1 - 6], fill=(70, 70, 80))
            for k in range(1, 4):
                y = o.y0 + (o.y1 - o.y0) * k // 4
                d.line([o.x0, y, o.x1, y], fill=(70, 70, 80))
            d.ellipse([o.x0 + 2, o.y1 - 10, o.x0 + 12, o.y1], fill=(30, 30, 30))
            d.ellipse([o.x1 - 12, o.y1 - 10, o.x1 - 2, o.y1], fill=(30, 30, 30))
        boxes.append(Box("shopper", o.x0, o.y0, o.x1, o.y1))
    return boxes


def coverage(b: Box, occluders: list[Occluder]) -> float:
    """Fraction of a box hidden behind occluders (union approximated by the max single overlap
    plus the rest, which is exact when occluders do not overlap each other)."""
    if not occluders or b.area <= 0:
        return 0.0
    covered = 0.0
    for o in occluders:
        ix = max(0.0, min(b.x1, o.x1) - max(b.x0, o.x0))
        iy = max(0.0, min(b.y1, o.y1) - max(b.y0, o.y0))
        covered += ix * iy
    return min(1.0, covered / b.area)


def degrade(img: Image.Image, light: Lighting, rng: np.random.Generator) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    arr[..., 0] *= 1 + light.warmth
    arr[..., 2] *= 1 - light.warmth
    arr *= light.brightness
    yy, xx = np.mgrid[0:IMG_H, 0:IMG_W]
    r = np.sqrt(((xx - IMG_W / 2) / (IMG_W / 2)) ** 2 + ((yy - IMG_H / 2) / (IMG_H / 2)) ** 2)
    arr *= (1 - light.vignette * np.clip(r - 0.4, 0, 1))[..., None]
    arr += rng.normal(0, light.noise, arr.shape)
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if light.blur > 0:
        out = out.filter(ImageFilter.GaussianBlur(light.blur))
    return out


def render_frame(
    bay: Bay,
    spec: FrameSpec,
    catalog: dict[str, Sku],
    h: np.ndarray,
    rng: np.random.Generator,
    keep_visible: float = 0.35,
) -> tuple[Image.Image, list[Box]]:
    """Full pipeline: frontal render -> camera perspective -> occluders -> lighting and noise.
    Labels hidden more than (1 - keep_visible) behind a shopper are dropped from the box list."""
    img, boxes = render_frontal(bay, spec.states, catalog, rng)
    img, boxes = warp(img, boxes, h)
    occ_boxes = draw_occluders(img, spec.occluders)
    kept = []
    for b in boxes:
        b.x0, b.y0 = max(0.0, b.x0), max(0.0, b.y0)
        b.x1, b.y1 = min(float(IMG_W), b.x1), min(float(IMG_H), b.y1)
        if b.area > 0 and coverage(b, spec.occluders) <= 1 - keep_visible:
            kept.append(b)
    return degrade(img, spec.lighting, rng), kept + occ_boxes


def yolo_label(boxes: list[Box]) -> str:
    rows = []
    for b in boxes:
        cx, cy = (b.x0 + b.x1) / 2 / IMG_W, (b.y0 + b.y1) / 2 / IMG_H
        w, hh = (b.x1 - b.x0) / IMG_W, (b.y1 - b.y0) / IMG_H
        if w <= 0 or hh <= 0:
            continue
        rows.append(f"{CLASS_ID[b.cls]} {cx:.5f} {cy:.5f} {w:.5f} {hh:.5f}")
    return "\n".join(rows) + ("\n" if rows else "")


def slot_image_rect(slot: Slot, h: np.ndarray) -> tuple[float, float, float, float]:
    """Where a slot's product region lands in the camera image."""
    return warp_rect(h, mm_to_px((slot.x0, slot.y1 - slot.pack_h, slot.x1, slot.y1)))
