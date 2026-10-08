"""HTTP API over the store twin for the 3D front end.

    uv run shelf-vision-api            # http://localhost:8020/api/state

Every call is serialised through one lock: the twin and the LangGraph thread inside it are
not thread-safe, and a frame step takes well under a second with cached detections."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .twin import Twin, plain

app = FastAPI(title="Shelf Vision twin API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_twin: Twin | None = None
_lock = threading.Lock()


def _get() -> Twin:
    global _twin
    if _twin is None:
        _twin = Twin()
    if _twin.frame < 0:
        _twin.step()
    return _twin


class StepBody(BaseModel):
    frames: int = 1


class DecideBody(BaseModel):
    task_id: str
    approve: bool


@app.get("/api/state")
def state(events: int = 120) -> dict[str, Any]:
    with _lock:
        return plain(_get().snapshot(events=events))


@app.post("/api/step")
def step(body: StepBody) -> dict[str, Any]:
    if not 1 <= body.frames <= 32:
        raise HTTPException(400, "frames must be between 1 and 32")
    with _lock:
        t = _get()
        last = {}
        for _ in range(body.frames):
            last = t.step()
        return plain({"result": last, "state": t.snapshot()})


@app.post("/api/decide")
def decide(body: DecideBody) -> dict[str, Any]:
    with _lock:
        t = _get()
        try:
            task = t.decide(body.task_id, body.approve)
        except KeyError as e:
            raise HTTPException(404, f"unknown task {body.task_id}") from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return plain({"task": task, "state": t.snapshot()})


@app.post("/api/reset")
def reset() -> dict[str, Any]:
    global _twin
    with _lock:
        _twin = None
        return plain(_get().snapshot())


@app.get("/api/trace/camera/{camera_id}")
def trace_camera(camera_id: str) -> dict[str, Any]:
    with _lock:
        try:
            return plain(_get().trace_camera(camera_id))
        except KeyError as e:
            raise HTTPException(404, f"unknown camera {camera_id}") from e


@app.get("/api/trace/slot/{slot_id}")
def trace_slot(slot_id: str) -> dict[str, Any]:
    with _lock:
        try:
            return plain(_get().trace_slot(slot_id))
        except KeyError as e:
            raise HTTPException(404, f"unknown slot {slot_id}") from e


@app.get("/api/trace/task/{task_id}")
def trace_task(task_id: str) -> dict[str, Any]:
    with _lock:
        try:
            return plain(_get().trace_task(task_id))
        except KeyError as e:
            raise HTTPException(404, f"unknown task {task_id}") from e


@app.get("/api/frame/{camera_id}/{t}.png")
def frame(camera_id: str, t: int, slot: str | None = None, boxes: bool = True) -> Response:
    with _lock:
        tw = _get()
        if not 0 <= t <= max(tw.frame, 0):
            raise HTTPException(404, f"frame {t} not reached yet")
        try:
            png = tw.frame_png(camera_id, t, slot_id=slot, boxes=boxes)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        return Response(content=png, media_type="image/png")


@app.get("/api/events")
def events(
    camera: str | None = None,
    slot: str | None = None,
    task: str | None = None,
    agent: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    with _lock:
        rows = _get().audit
        if camera:
            rows = [e for e in rows if e.get("camera") == camera]
        if slot:
            rows = [e for e in rows if e.get("slot") == slot]
        if task:
            rows = [e for e in rows if e.get("task") == task]
        if agent:
            rows = [e for e in rows if e.get("agent") == agent]
        return plain({"events": rows[-limit:]})


def main() -> None:
    import uvicorn

    uvicorn.run("shelf_vision.api:app", host="127.0.0.1", port=8020, log_level="warning")
