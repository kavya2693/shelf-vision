import uuid

from fastapi.testclient import TestClient
from langgraph.types import Command

from shelf_vision.config import REVIEW_CONFIDENCE
from shelf_vision.detector import OracleDetector
from shelf_vision.graph import build_graph
from shelf_vision.tasks import Task, check_inventory, propose_tasks
from shelf_vision.twin import Twin


def test_graph_runs_without_llm_and_issues_tasks(dataset):
    _, _, truth = dataset
    twin = Twin(detector=OracleDetector(truth), interactive=True)
    for _ in range(6):
        twin.step()
    agents = {a["agent"] for a in twin.audit}
    assert {
        "supervisor",
        "vision_agent",
        "compliance_agent",
        "merchandising_agent",
        "inventory_agent",
    } <= agents
    k = twin.kpis()
    assert 0 < k["compliance"] <= 1 and k["compliance"] <= k["osa"] <= 1
    assert k["tasks_total"] > 0 and k["pending_reviews"] == 0  # the oracle is confident
    assert twin.briefing.startswith("- Frame 5")
    task = next(iter(twin.tasks.values()))
    trace = twin.trace_task(task["task_id"])
    assert trace["slot"]["slot_id"] == task["slot_id"]
    assert all(s["done"] for s in trace["steps"] if s["name"] != "Stock checked")
    # Every task-producing audit row links camera, frame, slot, SKU and task.
    for a in twin.audit:
        if a["agent"] == "merchandising_agent":
            assert {"camera", "frame", "slot", "sku", "task"} <= set(a)


def test_human_review_pauses_and_resumes(dataset):
    plan, catalog, truth = dataset
    weak = OracleDetector(truth, conf=REVIEW_CONFIDENCE - 0.1)  # every finding needs a person
    g = build_graph(plan, catalog, weak)
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    state = None
    for frame in range(4):
        cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
        state = g.invoke(
            {"frame": frame, "interactive": True, "tracker": state.get("tracker_out", {}) if state else {}},
            cfg,
        )
        if "__interrupt__" in state:
            break
    assert state is not None and "__interrupt__" in state, "weak findings must pause the graph"
    pending = state["__interrupt__"][0].value["pending"]
    assert pending and "tasks" not in state
    first = pending[0]["task_id"]
    answers = {p["task_id"]: p["task_id"] == first for p in pending}  # approve one, reject the rest
    state = g.invoke(Command(resume=answers), cfg)
    tasks = {t["task_id"]: t for t in state["tasks"]}
    assert tasks[first]["state"] == "issued" and tasks[first]["review"] == "approved"
    assert all(tasks[p["task_id"]]["state"] == "rejected" for p in pending[1:])
    assert any(a["agent"] == "human_reviewer" for a in state["audit"])


def test_twin_decides_one_review_at_a_time(dataset):
    _, _, truth = dataset
    twin = Twin(detector=OracleDetector(truth, conf=0.3), interactive=True)
    while not twin.pending and not twin.done:
        twin.step()
    assert twin.pending
    n = len(twin.pending)
    first = twin.pending[0]["task_id"]
    twin.decide(first, True)
    assert len(twin.pending) == n - 1 or n == 1
    # Stepping on with undecided reviews leaves them pending, then a late decision still applies.
    twin.step()
    pend = [t for t in twin.all_tasks() if t["state"] == "pending_review"]
    issued = [t for t in twin.all_tasks() if t["task_id"] == first]
    assert issued[0]["state"] == "issued"
    if pend:
        twin.decide(pend[0]["task_id"], False)
        assert twin.tasks[pend[0]["task_id"]]["state"] == "rejected"


def test_tasks_prioritise_velocity_and_raise_replenishment(dataset):
    _, catalog, _ = dataset
    fast = max(catalog.values(), key=lambda s: s.velocity)
    slow = min(catalog.values(), key=lambda s: s.velocity)
    find = lambda sku, status: {  # noqa: E731
        "slot_id": f"X-{sku.sku}",
        "bay_id": "X",
        "camera_id": "CAM-X",
        "frame": 0,
        "expected_sku": sku.sku,
        "expected_facings": 2,
        "found_expected": 0,
        "status": status,
        "confidence": 0.9,
    }
    tasks = propose_tasks([find(slow, "out_of_stock"), find(fast, "out_of_stock")], catalog, 1, {})
    assert [t.sku for t in tasks] == [fast.sku, slow.sku]
    assert all(t.type == "restock" and t.state == "issued" for t in tasks)
    stock = {fast.sku: {"backroom": 10, "dc": 0}, slow.sku: {"backroom": 0, "dc": 0}}
    tasks, requests, after = check_inventory(tasks, catalog, stock, 1)
    assert after[fast.sku]["backroom"] == 10 - tasks[0].qty and tasks[0].source == "backroom"
    assert tasks[1].source == "replenishment" and len(requests) == 1
    po = requests[0]
    assert po["po_id"] == "RR-0001" and po["sku"] == slow.sku and po["qty"] == slow.moq
    assert {
        "po_id",
        "sku",
        "family",
        "source",
        "status",
        "qty",
        "moq",
        "unit_cost",
        "value",
        "lead_time_weeks",
    } <= set(po)
    weak = propose_tasks([{**find(fast, "missing_tag"), "confidence": 0.3}], catalog, 5, {})[0]
    assert weak.state == "pending_review" and weak.task_id == "TSK-0005"
    assert Task(**weak.to_dict()) == weak


def test_api_serves_state_traces_and_frames(dataset, monkeypatch):
    from shelf_vision import api

    _, _, truth = dataset
    monkeypatch.setattr(api, "_twin", Twin(detector=OracleDetector(truth), interactive=True))
    c = TestClient(api.app)
    s = c.get("/api/state").json()
    assert s["frame"] == 0 and len(s["slots"]) == 90 and len(s["cameras"]) == 6
    s = c.post("/api/step", json={"frames": 4}).json()["state"]
    assert s["frame"] == 4 and s["kpis"]["tasks_total"] > 0
    cam = c.get("/api/trace/camera/CAM-1L").json()
    assert cam["frame"] == 4 and cam["detections"]
    slot = c.get(f"/api/trace/slot/{s['slots'][0]['slot_id']}").json()
    assert slot["planogram"]["sku"] == s["slots"][0]["sku"] and slot["timeline"]
    task = c.get(f"/api/trace/task/{s['tasks'][0]['task_id']}").json()
    assert task["steps"] and task["frame_url"].startswith("/api/frame/")
    png = c.get(task["frame_url"])
    assert (
        png.status_code == 200
        and png.headers["content-type"] == "image/png"
        and png.content[:4] == b"\x89PNG"
    )
    assert c.get("/api/trace/task/TSK-9999").status_code == 404
    assert c.get("/api/frame/CAM-1L/15.png").status_code == 404
