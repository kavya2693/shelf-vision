"""The agentic workflow: a supervisor plus four collaborating agents in LangGraph, run once
per frame step.

    supervisor ─► vision_agent ─► supervisor ─► compliance_agent ─► supervisor
               ─► merchandising_agent ─► [human review interrupt] ─► supervisor
               ─► inventory_agent ─► supervisor ─► END

Agents share one state object and append to an audit trail, so every task can be traced to
the camera, frame, slot and SKU that produced it. The detector and the planogram are injected
at build time; nothing in the state is a Python object, so the checkpointer can persist it."""

from __future__ import annotations

import operator
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from .catalog import FAMILY_BY_SHORT, Sku
from .compliance import SlotTracker, compliance_metrics, observe
from .config import PERSIST_FRAMES
from .detector import Detector
from .llm import get_llm
from .pipeline import frame_path
from .planogram import Planogram
from .tasks import Task, check_inventory, propose_tasks


class State(TypedDict, total=False):
    frame: int
    interactive: bool
    smoothing: bool  # False replays raw per-frame statuses (used by the evaluation)
    tracker: dict  # slot tracker state carried in from the previous frame
    open_slots: list[str]  # slots that already have an open task
    stock: dict[str, dict[str, int]]
    next_task: int
    next_request: int
    done: Annotated[list[str], operator.add]
    audit: Annotated[list[dict], operator.add]
    detections: dict[str, list[dict]]
    observations: list[dict]
    tracker_out: dict
    statuses: dict[str, str]
    confidences: dict[str, float]
    findings: list[dict]
    compliance: dict
    tasks: list[dict]
    replenishment: list[dict]
    stock_out: dict[str, dict[str, int]]
    briefing: str
    next: str


def _log(agent: str, action: str, **detail: Any) -> list[dict]:
    return [
        {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "agent": agent, "action": action, **detail}
    ]


def build_graph(plan: Planogram, catalog: dict[str, Sku], detector: Detector):
    foreign_names = {k: v.name for k, v in FAMILY_BY_SHORT.items()}

    # ── Supervisor ───────────────────────────────────────────────────────────
    def supervisor(state: State) -> dict:
        done = set(state.get("done", []))
        if "vision" not in done:
            nxt = "vision_agent"
        elif "compliance" not in done:
            nxt = "compliance_agent"
        elif "merchandising" not in done:
            nxt = "merchandising_agent"
        elif "inventory" not in done:
            nxt = "inventory_agent"
        else:
            nxt = END
        return {"next": nxt, "audit": _log("supervisor", "route", to=str(nxt), frame=state["frame"])}

    # ── 1. Vision agent: run the detector on this frame for every camera ─────
    def vision_agent(state: State) -> dict:
        t = state["frame"]
        dets = {
            c.camera_id: [d.to_dict() for d in detector.detect(frame_path(c.camera_id, t))]
            for c in plan.cameras
        }
        return {
            "done": ["vision"],
            "detections": dets,
            "audit": [
                _log("vision_agent", "detect", camera=c, frame=t, detector=detector.name, boxes=len(v))[0]
                for c, v in dets.items()
            ],
        }

    # ── 2. Compliance agent: slot geometry, status, temporal confirmation ────
    def compliance_agent(state: State) -> dict:
        t = state["frame"]
        tracker = SlotTracker(PERSIST_FRAMES if state.get("smoothing", True) else 1, state.get("tracker"))
        observations, statuses, confidences, findings, audit = [], {}, {}, [], []
        open_slots = set(state.get("open_slots", []))
        for cam, dets in state["detections"].items():
            from .detector import Detection

            obs = observe(plan, catalog, cam, t, [Detection.from_dict(d) for d in dets])
            for o in obs:
                track = tracker.update(o)
                statuses[o.slot_id] = track.confirmed
                confidences[o.slot_id] = round(track.confidence, 3)
                observations.append(o.to_dict())
                if track.confirmed != "ok" and o.slot_id not in open_slots:
                    findings.append(
                        {
                            **o.to_dict(),
                            "status": track.confirmed,
                            "confidence": track.confidence,
                            "confirmed_frame": track.confirmed_frame,
                        }
                    )
            unobserved = sum(not o.observed for o in obs)
            audit += _log(
                "compliance_agent",
                "match_planogram",
                camera=cam,
                frame=t,
                slots=len(obs),
                faults={
                    s: sum(1 for o in obs if statuses[o.slot_id] == s)
                    for s in ("out_of_stock", "misplaced", "wrong_facings", "missing_tag")
                },
                occluded=unobserved,
            )
        metrics = compliance_metrics(statuses, plan)
        audit += _log(
            "compliance_agent",
            "score",
            frame=t,
            compliance=metrics["compliance"],
            osa=metrics["osa"],
            new_findings=len(findings),
        )
        return {
            "done": ["compliance"],
            "observations": observations,
            "tracker_out": tracker.to_dict(),
            "statuses": statuses,
            "confidences": confidences,
            "findings": findings,
            "compliance": metrics,
            "audit": audit,
        }

    # ── 3. Merchandising agent: findings -> prioritised tasks, human review ──
    def merchandising_agent(state: State) -> dict:
        t = state["frame"]
        tasks = propose_tasks(state.get("findings", []), catalog, state.get("next_task", 1), foreign_names)
        audit = [
            _log(
                "merchandising_agent",
                "propose_task",
                frame=t,
                task=k.task_id,
                type=k.type,
                slot=k.slot_id,
                sku=k.sku,
                camera=k.camera_id,
                priority=k.priority,
                review=k.review,
                confidence=k.confidence,
            )[0]
            for k in tasks
        ]
        pending = [k for k in tasks if k.review == "pending"]
        while pending and state.get("interactive"):
            # Human in the loop: findings resting on weak evidence (no gap detected, a missing
            # detection) pause the graph until a person has looked at the frame. The reviewer may
            # answer all at once (CLI) or one task per resume (the twin); undecided tasks stay
            # pending if the reviewer closes the queue.
            answers = dict(
                interrupt(
                    {
                        "frame": t,
                        "pending": [
                            {
                                "task_id": k.task_id,
                                "type": k.type,
                                "slot_id": k.slot_id,
                                "sku": k.sku,
                                "camera_id": k.camera_id,
                                "finding": k.finding,
                                "confidence": k.confidence,
                                "instruction": k.instruction,
                            }
                            for k in pending
                        ],
                    }
                )
            )
            close = bool(answers.pop("__close__", False))
            for k in tasks:
                if k.task_id in answers:
                    ok = bool(answers[k.task_id])
                    k.review = "approved" if ok else "rejected"
                    k.state = "issued" if ok else "rejected"
                    audit += _log(
                        "human_reviewer",
                        "decide",
                        frame=t,
                        task=k.task_id,
                        slot=k.slot_id,
                        sku=k.sku,
                        camera=k.camera_id,
                        approved=ok,
                    )
            pending = [k for k in tasks if k.review == "pending"]
            if close:
                break
        return {"done": ["merchandising"], "tasks": [k.to_dict() for k in tasks], "audit": audit}

    # ── 4. Inventory agent: backroom, DC, or a replenishment request ─────────
    def inventory_agent(state: State) -> dict:
        t = state["frame"]
        tasks = [Task(**d) for d in state.get("tasks", [])]
        tasks, requests, stock = check_inventory(
            tasks, catalog, state.get("stock", {}), state.get("next_request", 1)
        )
        audit = [
            _log(
                "inventory_agent",
                "check_stock",
                frame=t,
                task=k.task_id,
                slot=k.slot_id,
                sku=k.sku,
                camera=k.camera_id,
                source=k.source,
                qty=k.qty,
            )[0]
            for k in tasks
            if k.type == "restock" and k.state == "issued"
        ]
        audit += [
            _log(
                "inventory_agent",
                "raise_replenishment",
                frame=t,
                request=r["po_id"],
                sku=r["sku"],
                qty=r["qty"],
                value=r["value"],
                task=r["task_id"],
                slot=r["slot_id"],
                camera=r["camera_id"],
            )[0]
            for r in requests
        ]
        return {
            "done": ["inventory"],
            "tasks": [k.to_dict() for k in tasks],
            "replenishment": requests,
            "stock_out": stock,
            "briefing": _briefing(state, tasks, requests),
            "audit": audit,
        }

    g = StateGraph(State)
    g.add_node("supervisor", supervisor)
    for name, fn in (
        ("vision_agent", vision_agent),
        ("compliance_agent", compliance_agent),
        ("merchandising_agent", merchandising_agent),
        ("inventory_agent", inventory_agent),
    ):
        g.add_node(name, fn)
        g.add_edge(name, "supervisor")
    g.set_entry_point("supervisor")
    g.add_conditional_edges(
        "supervisor",
        lambda s: s["next"],
        ["vision_agent", "compliance_agent", "merchandising_agent", "inventory_agent", END],
    )
    return g.compile(checkpointer=MemorySaver())


def _briefing(state: State, tasks: list[Task], requests: list[dict]) -> str:
    m = state.get("compliance", {})
    notes = [
        f"Frame {state['frame']}: planogram compliance {m.get('compliance', 0):.0%}, "
        f"on-shelf availability {m.get('osa', 0):.0%}, {m.get('gaps', 0)} empty slots.",
    ]
    issued = [k for k in tasks if k.state == "issued"]
    if issued:
        by: dict[str, int] = {}
        for k in issued:
            by[k.type] = by.get(k.type, 0) + 1
        notes.append("Tasks issued: " + ", ".join(f"{v} {k}" for k, v in sorted(by.items())) + ".")
    pending = [k for k in tasks if k.state == "pending_review"]
    if pending:
        notes.append(f"{len(pending)} finding(s) on weak evidence wait for a reviewer.")
    if requests:
        notes.append(f"{len(requests)} replenishment request(s) raised: no stock in the store or the DC.")
    llm = get_llm()
    if llm is not None:
        try:
            msg = llm.invoke(
                "You are a store operations assistant. Write a 4-bullet shift note for the store "
                "manager from these facts. Do not invent or change any number.\n" + "\n".join(notes)
            )
            return str(msg.content)
        except Exception as e:  # the workflow must never fail on the narrative
            return f"(LLM unavailable: {type(e).__name__}) " + " ".join(notes)
    return "\n".join(f"- {n}" for n in notes)
