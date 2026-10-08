# Architecture

Shelf Vision is four layers, each of which can be run and tested on its own: a seeded data
generator, a small object detector, a deterministic compliance and merchandising core wrapped
in a LangGraph supervisor, and a store twin that steps through the camera frames and serves
the 3D front end.

```
 data/                       src/shelf_vision/                    twin/ (Vite + React + R3F)
 ┌───────────────┐   train   ┌──────────────┐  boxes  ┌────────────────────────┐
 │ yolo/ train   │──────────►│ detector.py  │────────►│ graph.py               │
 │  val, test    │           │ YOLOv8n, CPU │         │  supervisor            │
 ├───────────────┤  detect   │ oracle       │         │  ├ vision_agent        │
 │ sequence/     │──────────►│ cached       │         │  ├ compliance_agent ───┼──► compliance.py
 │  CAM-*/frames │           └──────────────┘         │  ├ merchandising_agent─┼──► tasks.py
 │  ground_truth │                                    │  │   interrupt()       │
 └───────────────┘                                    │  └ inventory_agent ────┼──► tasks.py
        ▲                                             └──────────┬─────────────┘
        │ generate                                               │ per frame
 catalog.py ─ planogram.py ─ render.py ─ data.py            twin.py ──► api.py ──► twin/src
```

## 1. Data (`catalog.py`, `planogram.py`, `render.py`, `data.py`)

- **Catalogue.** 45 SKUs, five per family, over the nine retail families of
  agentic-supply-planning. Each SKU has a colour near its family hue, a pack shape, a pack
  size in millimetres, a velocity, a unit cost, a lead time, an MOQ and backroom/DC stock.
  Stock levels are drawn from a separate seed so a stocking-policy change never alters the
  rendered images.
- **Planogram.** One store, three aisles, two bays per aisle, three shelves of five slots:
  90 slots, each naming its SKU, facings and a price tag. Slot geometry is in bay-plane
  millimetres. The planogram is JSON (`data/planogram.json`) with the per-camera homography
  recorded after the sequences are rendered.
- **Rendering.** A bay is drawn face-on (shelf back, boards with a tag rail, packs as shaped
  blocks with a label, price tags), then warped by a fixed per-camera homography, then
  shoppers and trolleys are drawn over it, then lighting drift, vignette, sensor noise and
  blur are applied. Every box comes from the drawing code, so labels are exact by
  construction; packs more than 65% hidden lose their label.
- **Two datasets.** A training set of 360 random bays with random faults, cameras and
  shoppers (240/60/60 split by index), and six 16-frame deployment sequences for the twin,
  with faults injected at scheduled frames that persist, shoppers passing for one or two
  frames, and per-frame ground truth for every slot.

## 2. Detector (`detector.py`)

YOLOv8n fine-tuned from the COCO checkpoint on CPU: 512 px, 30 epochs, batch 16, no
horizontal flips (they would teach mirrored price tags), light HSV jitter. Twelve classes:
nine families, `gap`, `price_tag`, `shopper`. Evaluation on the held-out test split writes
`outputs/metrics/detector.json` including per-class AP, so the weak class is visible.

Three implementations share one protocol, `detect(path) -> list[Detection]`:
`YoloDetector` (the model), `CachedDetector` (the boxes `shelf-vision detect` wrote for the
deployment frames, so the API never loads torch) and `OracleDetector` (ground-truth boxes
at a fixed confidence, for tests and as an upper bound).

## 3. Compliance (`compliance.py`)

`observe()` inverts the camera homography on each box, assigns it to the slot (or tag rail)
it overlaps most on the bay plane, and counts per slot: expected-family boxes, foreign boxes,
gap coverage, tag seen, and how much of the slot the detected shopper boxes cover. The raw
status follows the planogram definition in priority order: out of stock, misplaced, short
facings, missing tag, ok. Evidence confidence is the mean box confidence, or a fixed weak
value when the finding rests on an absence.

`SlotTracker` carries a candidate status and a streak per slot across frames; a change is
confirmed after `PERSIST_FRAMES` (3) consecutive observed frames agree. Frames where the slot
is more than 35% hidden behind a shopper box neither advance nor reset the streak. The tracker
state is plain dicts so it rides in the LangGraph state between frames.

`compliance_metrics()` defines compliance (slots exactly as planned) and on-shelf
availability (slots whose planned product is present at all).

## 4. Agents (`graph.py`, `tasks.py`)

One LangGraph `StateGraph` per frame step with a `MemorySaver` checkpointer:

| Node | Does | Deterministic tool |
|---|---|---|
| supervisor | routes vision -> compliance -> merchandising -> inventory -> END | - |
| vision_agent | runs the injected detector on this frame for every camera | detector |
| compliance_agent | observe + tracker update, compliance metrics, new findings (confirmed faults on slots with no open task) | `compliance.py` |
| merchandising_agent | one task per finding, priority = family velocity x task weight; weak-evidence tasks `interrupt()` for a reviewer | `tasks.propose_tasks` |
| inventory_agent | reserve backroom stock, else DC transfer, else a replenishment request in the supply-planning PO format | `tasks.check_inventory` |

Every node appends to `audit` with the camera, frame, slot, SKU and task it touched. The
briefing at the end is a plain-text summary, or an LLM rewrite of the same facts when a key
or a local Ollama is present; the workflow never depends on it.

## 5. Twin and API (`twin.py`, `api.py`)

`Twin` is the clock. `step()` runs the graph for the next frame with the tracker state, the
open tasks, the stock and the id counters carried in; `_absorb()` merges the result. If the
graph pauses on an interrupt, the pending reviews are exposed and `decide(task_id, ok)`
resumes the same thread with one answer; stepping on with undecided reviews closes the
queue (they stay pending and can be decided later, applied directly and logged the same
way). Traces (`trace_camera`, `trace_slot`, `trace_task`) assemble the planogram, the latest
observation, the tracker, the timeline, the tasks, the requests and the audit rows for one
object, and `frame_png()` draws the cached boxes (and a slot outline) on the stored frame.

FastAPI serialises every call through one lock and exposes `/api/state`, `/api/step`,
`/api/decide`, `/api/reset`, `/api/trace/{camera,slot,task}/{id}`, `/api/frame/{cam}/{t}.png`
and `/api/events`.

## 6. Front end (`twin/`)

Vite, React, TypeScript, @react-three/fiber and drei, zustand. The world has the sales
floor with three gondola runs (each aisle's left and right bay side by side facing the
walkway), a camera on a pole per bay with a view cone, the backroom with one pallet stack
per family sized by units on hand, the distribution centre at the end of the service road,
and a control room with one station per agent that lights up as the audit feed grows.
Everything picks into one `selection`; the trace panel fetches the matching trace. The clock
steps frames; the bottom panel holds the review queue (Approve/Reject), the task list, the
replenishment requests and the audit feed.

## 7. Evaluation (`evaluate.py`)

Runs the compliance pipeline over all deployment frames with the cached detections twice,
with the tracker at persistence 1 (raw) and 3 (smoothed), and scores against ground truth:
status accuracy, false-alert rate (overall and on occluded slot-frames), miss rate, confusion
matrix and mean time-to-detect per injected fault. Written to `outputs/metrics/pipeline.json`
and shown on the KPI cards.
