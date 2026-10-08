"""The product universe: the nine retail families of the sibling supply-planning project
(agentic-supply-planning, RETAIL domain), each with a pack shape and a colour family the
renderer draws and the detector learns. SKUs are seeded so the same catalogue is produced
on every machine and the same `RTL-nnnn` ids can be quoted in replenishment requests."""

from dataclasses import asdict, dataclass

import numpy as np

from .config import SEED


@dataclass(frozen=True)
class Family:
    name: str
    short: str  # detector class name and label stem
    shape: str  # bottle | box | bag | tub | jug | tube | blister | carton
    hue: float  # base hue in degrees; SKUs vary a little around it
    pack_mm: tuple[int, int]  # width, height of one facing
    velocity: float  # weekly store units for a typical SKU (base_units in the sibling project)
    unit_cost: float
    lead_weeks: int
    moq: int
    perishable: bool = False


# Hues are spread around the wheel so each family is separable by colour at CCTV resolution.
FAMILIES: tuple[Family, ...] = (
    Family("Fresh Produce", "produce", "bag", 110, (95, 140), 140, 1.2, 1, 48, perishable=True),
    Family("Dairy & Bakery", "dairy", "tub", 200, (85, 100), 150, 1.6, 1, 48, perishable=True),
    Family("Beverages", "beverage", "bottle", 15, (58, 230), 170, 0.9, 2, 96),
    Family("Snacks & Confectionery", "snacks", "box", 45, (95, 180), 130, 1.1, 2, 96),
    Family("Personal Care", "personal_care", "tube", 300, (48, 190), 55, 3.5, 3, 96),
    Family("Household Cleaning", "household", "jug", 180, (90, 250), 50, 2.8, 3, 96),
    Family("Baby & Kids", "baby", "carton", 330, (120, 210), 35, 6.0, 4, 48),
    Family("Home & Kitchen", "home_kitchen", "box", 30, (140, 160), 18, 9.0, 8, 240),
    Family("Electronics Accessories", "electronics", "blister", 240, (68, 150), 12, 14.0, 8, 240),
)
FAMILY_BY_NAME = {f.name: f for f in FAMILIES}
FAMILY_BY_SHORT = {f.short: f for f in FAMILIES}

# Detector classes: one per family, plus the empty-facing region, the price tag and the shopper.
CLASS_NAMES: tuple[str, ...] = (*(f.short for f in FAMILIES), "gap", "price_tag", "shopper")
CLASS_ID = {n: i for i, n in enumerate(CLASS_NAMES)}

SKUS_PER_FAMILY = 5


@dataclass(frozen=True)
class Sku:
    sku: str
    family: str
    short: str
    shape: str
    rgb: tuple[int, int, int]
    pack_mm: tuple[int, int]
    velocity: float
    unit_cost: float
    price: float
    lead_time_weeks: int
    moq: int
    backroom: int  # units in the store backroom
    dc: int  # units at the distribution centre
    perishable: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    import colorsys

    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def build_catalog(seed: int = SEED) -> list[Sku]:
    rng = np.random.default_rng(seed)
    # Stock levels come from their own stream, so changing the stocking policy never changes
    # the colours and pack sizes the detector was trained on.
    stock_rng = np.random.default_rng(seed + 7)
    out: list[Sku] = []
    i = 0
    for fam in FAMILIES:
        for _ in range(SKUS_PER_FAMILY):
            hue = fam.hue + rng.uniform(-14, 14)
            sat = rng.uniform(0.55, 0.9)
            val = rng.uniform(0.6, 0.95)
            w, h = fam.pack_mm
            size = rng.uniform(0.85, 1.15)
            cost = round(fam.unit_cost * rng.uniform(0.7, 1.4), 2)
            # Some SKUs have no stock anywhere, so the inventory agent has to raise a replenishment.
            stocked = stock_rng.random()
            backroom, dc = int(stock_rng.integers(4, 40)), int(stock_rng.integers(50, 400))
            if stocked < 0.4:
                backroom = 0
            if stocked < 0.22:
                dc = 0
            out.append(
                Sku(
                    sku=f"RTL-{i:04d}",
                    family=fam.name,
                    short=fam.short,
                    shape=fam.shape,
                    rgb=_hsv_to_rgb(hue, sat, val),
                    pack_mm=(int(w * size), min(int(h * size), 280)),
                    velocity=round(float(fam.velocity * rng.lognormal(0, 0.35)), 1),
                    unit_cost=cost,
                    price=round(cost * 1.35, 2),
                    lead_time_weeks=fam.lead_weeks,
                    moq=fam.moq,
                    backroom=backroom,
                    dc=dc,
                    perishable=fam.perishable,
                )
            )
            i += 1
    return out


def sku_from_dict(d: dict) -> Sku:
    d = dict(d)
    d["rgb"] = tuple(d["rgb"])
    d["pack_mm"] = tuple(d["pack_mm"])
    return Sku(**d)
