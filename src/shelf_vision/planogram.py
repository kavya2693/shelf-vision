"""The planogram: store -> aisle -> bay -> shelf -> slot, each slot naming the SKU that belongs
there, how many facings it gets and whether it carries a price tag. Slot geometry is in
bay-plane millimetres (x to the right, y downward from the top of the bay), which is the
plane the camera homography maps image pixels back to."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .catalog import FAMILIES, Sku, build_catalog, sku_from_dict
from .config import (
    BAY_WIDTH_MM,
    DATA,
    N_AISLES,
    SEED,
    SHELF_BOARD_MM,
    SHELF_PITCH_MM,
    SHELVES_PER_BAY,
    SIDES,
    SLOTS_PER_SHELF,
)

SLOT_MARGIN_MM = 12
TAG_MM = (100, 30)
BAY_HEIGHT_MM = SHELVES_PER_BAY * SHELF_PITCH_MM
SLOT_WIDTH_MM = BAY_WIDTH_MM // SLOTS_PER_SHELF


@dataclass
class Slot:
    slot_id: str
    bay_id: str
    shelf: int  # 0 = top shelf
    index: int  # 0 = leftmost slot
    sku: str
    facings: int
    has_tag: bool
    x0: int  # slot rectangle in bay-plane mm
    y0: int
    x1: int
    y1: int
    pack_w: int
    pack_h: int

    @property
    def board_y(self) -> int:
        """Top of the shelf board the products stand on."""
        return self.y1

    def facing_rect(self, j: int) -> tuple[int, int, int, int]:
        x = self.x0 + SLOT_MARGIN_MM + j * self.pack_w
        return x, self.board_y - self.pack_h, x + self.pack_w, self.board_y

    def tag_rect(self) -> tuple[int, int, int, int]:
        x = self.x0 + SLOT_MARGIN_MM
        y = self.board_y + (SHELF_BOARD_MM - TAG_MM[1]) // 2
        return x, y, x + TAG_MM[0], y + TAG_MM[1]


@dataclass
class Bay:
    bay_id: str
    aisle: int
    side: str
    camera_id: str
    families: list[str]
    slots: list[Slot] = field(default_factory=list)


@dataclass
class Camera:
    camera_id: str
    bay_id: str
    homography: list[list[float]]  # frontal bay-plane pixels -> image pixels
    label: str


@dataclass
class Planogram:
    store: str
    bays: list[Bay]
    cameras: list[Camera]

    def slot(self, slot_id: str) -> Slot:
        for b in self.bays:
            for s in b.slots:
                if s.slot_id == slot_id:
                    return s
        raise KeyError(slot_id)

    def bay(self, bay_id: str) -> Bay:
        for b in self.bays:
            if b.bay_id == bay_id:
                return b
        raise KeyError(bay_id)

    def camera(self, camera_id: str) -> Camera:
        for c in self.cameras:
            if c.camera_id == camera_id:
                return c
        raise KeyError(camera_id)

    def bay_for_camera(self, camera_id: str) -> Bay:
        return self.bay(self.camera(camera_id).bay_id)

    @property
    def slots(self) -> list[Slot]:
        return [s for b in self.bays for s in b.slots]

    def to_dict(self) -> dict:
        return {
            "store": self.store,
            "bays": [asdict(b) for b in self.bays],
            "cameras": [asdict(c) for c in self.cameras],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Planogram:
        bays = [Bay(**{**b, "slots": [Slot(**s) for s in b["slots"]]}) for b in d["bays"]]
        return cls(d["store"], bays, [Camera(**c) for c in d["cameras"]])


def facings_for(sku: Sku, rng: np.random.Generator) -> int:
    usable = SLOT_WIDTH_MM - 2 * SLOT_MARGIN_MM
    most = max(1, usable // sku.pack_mm[0])
    if most <= 1:
        return 1
    # Shelves are planned full: a slot gets its maximum or one fewer, never a lone facing.
    return int(rng.integers(max(2, most - 1), most + 1))


def make_slot(bay_id: str, shelf: int, index: int, sku: Sku, facings: int, has_tag: bool) -> Slot:
    x0 = index * SLOT_WIDTH_MM
    y1 = (shelf + 1) * SHELF_PITCH_MM - SHELF_BOARD_MM
    return Slot(
        slot_id=f"{bay_id}-S{shelf}-{index}",
        bay_id=bay_id,
        shelf=shelf,
        index=index,
        sku=sku.sku,
        facings=facings,
        has_tag=has_tag,
        x0=x0,
        y0=shelf * SHELF_PITCH_MM + 20,
        x1=x0 + SLOT_WIDTH_MM,
        y1=y1,
        pack_w=sku.pack_mm[0],
        pack_h=sku.pack_mm[1],
    )


def fill_bay(bay: Bay, catalog: list[Sku], rng: np.random.Generator) -> None:
    """Assign SKUs from the bay's families to its slots. Price tags are planned on every slot;
    whether one is actually present is a frame-level fault, not a planogram fact."""
    pool = [s for s in catalog if s.family in bay.families]
    bay.slots = []
    for shelf in range(SHELVES_PER_BAY):
        for index in range(SLOTS_PER_SHELF):
            sku = pool[int(rng.integers(len(pool)))]
            bay.slots.append(make_slot(bay.bay_id, shelf, index, sku, facings_for(sku, rng), True))


def random_bay(bay_id: str, catalog: list[Sku], rng: np.random.Generator, camera_id: str = "CAM") -> Bay:
    """A bay with one or two random families, used for the training set."""
    n = int(rng.integers(1, 3))
    fams = [FAMILIES[i].name for i in rng.choice(len(FAMILIES), size=n, replace=False)]
    bay = Bay(bay_id, 0, "L", camera_id, fams)
    fill_bay(bay, catalog, rng)
    return bay


def build_planogram(catalog: list[Sku], seed: int = SEED) -> Planogram:
    """The store the twin watches: three aisles, a bay per side, two families per bay."""
    rng = np.random.default_rng(seed + 1)
    order = list(rng.permutation(len(FAMILIES)))
    bays, cameras = [], []
    k = 0
    for aisle in range(N_AISLES):
        for side in SIDES:
            bay_id = f"A{aisle + 1}{side}"
            cam_id = f"CAM-{aisle + 1}{side}"
            fams = [FAMILIES[order[k % len(order)]].name, FAMILIES[order[(k + 4) % len(order)]].name]
            k += 1
            bay = Bay(bay_id, aisle + 1, side, cam_id, fams)
            fill_bay(bay, catalog, rng)
            bays.append(bay)
            cameras.append(
                Camera(cam_id, bay_id, [], f"Aisle {aisle + 1} {'left' if side == 'L' else 'right'}")
            )
    return Planogram("Store 01", bays, cameras)


def save_catalog(catalog: list[Sku], path: Path = DATA / "catalog.json") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([s.to_dict() for s in catalog], indent=1))


def load_catalog(path: Path = DATA / "catalog.json") -> list[Sku]:
    if not path.exists():
        return build_catalog()
    return [sku_from_dict(d) for d in json.loads(path.read_text())]


def save_planogram(p: Planogram, path: Path = DATA / "planogram.json") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p.to_dict(), indent=1))


def load_planogram(path: Path = DATA / "planogram.json") -> Planogram:
    return Planogram.from_dict(json.loads(path.read_text()))
