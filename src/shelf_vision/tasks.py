"""Deterministic merchandising and inventory tools. Every task, priority, quantity and
replenishment request is computed here, never by a language model, so each one can be
traced back to the frame and slot that caused it."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .catalog import Sku
from .compliance import family_velocity
from .config import REVIEW_CONFIDENCE, TASK_WEIGHT, UNITS_PER_FACING

TASK_FOR_STATUS = {
    "out_of_stock": "restock",
    "misplaced": "relocate",
    "wrong_facings": "reface",
    "missing_tag": "fix_tag",
}
INSTRUCTION = {
    "restock": "Bring {qty} units of {sku} ({family}) from the backroom and fill {slot}",
    "relocate": "Remove the {foreign} pack from {slot} and return it to its own bay; re-face {sku}",
    "reface": "Pull {sku} forward and top up {slot} to {facings} facings",
    "fix_tag": "Print and fit the price tag for {sku} at {slot}",
}


@dataclass
class Task:
    task_id: str
    type: str
    slot_id: str
    bay_id: str
    camera_id: str
    frame: int
    sku: str
    family: str
    finding: str
    confidence: float
    priority: float
    qty: int
    instruction: str
    review: str  # auto | pending | approved | rejected
    state: str  # issued | pending_review | rejected
    source: str | None = None  # backroom | dc | replenishment (restock tasks only)
    request_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def propose_tasks(
    findings: list[dict], catalog: dict[str, Sku], next_id: int, foreign_names: dict[str, str]
) -> list[Task]:
    """One task per confirmed finding, prioritised by the family's sales velocity (a gap on a
    fast mover loses more sales per hour than a gap on a slow one) times the task's weight."""
    tasks = []
    for i, f in enumerate(sorted(findings, key=lambda f: f["slot_id"])):
        sku = catalog[f["expected_sku"]]
        kind = TASK_FOR_STATUS[f["status"]]
        missing = f["expected_facings"] - min(f.get("found_expected", 0), f["expected_facings"])
        qty = max(1, missing) * UNITS_PER_FACING if kind in ("restock", "reface") else 0
        priority = round(family_velocity(sku) * TASK_WEIGHT[kind], 1)
        text = INSTRUCTION[kind].format(
            qty=qty,
            sku=sku.sku,
            family=sku.family,
            slot=f["slot_id"],
            facings=f["expected_facings"],
            foreign=foreign_names.get(f.get("foreign_family") or "", "foreign"),
        )
        weak = f["confidence"] < REVIEW_CONFIDENCE
        tasks.append(
            Task(
                task_id=f"TSK-{next_id + i:04d}",
                type=kind,
                slot_id=f["slot_id"],
                bay_id=f["bay_id"],
                camera_id=f["camera_id"],
                frame=f["frame"],
                sku=sku.sku,
                family=sku.family,
                finding=f["status"],
                confidence=round(f["confidence"], 3),
                priority=priority,
                qty=qty,
                instruction=text,
                review="pending" if weak else "auto",
                state="pending_review" if weak else "issued",
            )
        )
    return sorted(tasks, key=lambda t: (-t.priority, t.task_id))


def check_inventory(
    tasks: list[Task], catalog: dict[str, Sku], stock: dict[str, dict[str, int]], next_request: int
) -> tuple[list[Task], list[dict], dict[str, dict[str, int]]]:
    """Reserve backroom stock for issued restock tasks, fall back to a DC transfer, and raise a
    replenishment request in the supply-planning project's purchase-order format when neither
    holds the SKU. Returns the updated tasks, the requests and the stock after reservations."""
    stock = {k: dict(v) for k, v in stock.items()}
    requests = []
    for t in tasks:
        if t.type != "restock" or t.state != "issued":
            continue
        s = stock.setdefault(t.sku, {"backroom": 0, "dc": 0})
        if s["backroom"] >= t.qty:
            s["backroom"] -= t.qty
            t.source = "backroom"
        elif s["dc"] >= t.qty:
            s["dc"] -= t.qty
            t.source = "dc"
            t.instruction = (
                f"No backroom stock: transfer {t.qty} units of {t.sku} from the DC, then fill {t.slot_id}"
            )
        else:
            sku = catalog[t.sku]
            rid = f"RR-{next_request:04d}"
            next_request += 1
            t.source = "replenishment"
            t.request_id = rid
            t.instruction = (
                f"No stock in store or DC: replenishment {rid} raised for {t.sku}; face with a neighbour"
            )
            requests.append(
                {
                    "po_id": rid,
                    "sku": sku.sku,
                    "family": sku.family,
                    "source": "Shelf gap (CCTV)",
                    "status": "critical",
                    "stockout_week": 0,
                    "qty": sku.moq,
                    "moq": sku.moq,
                    "unit_cost": sku.unit_cost,
                    "value": round(sku.moq * sku.unit_cost, 2),
                    "lead_time_weeks": sku.lead_time_weeks,
                    "within_budget": True,
                    "slot_id": t.slot_id,
                    "task_id": t.task_id,
                    "camera_id": t.camera_id,
                    "frame": t.frame,
                }
            )
    return tasks, requests, stock
