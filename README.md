# shelf-vision

CCTV frames turned into planogram compliance, prioritised store tasks and replenishment
requests by a small detector, deterministic slot matching and four LangGraph agents, with a
3D store twin to trace every task back to the frame that caused it.

**Status: work in progress.** The data generator, detector training, compliance
evaluation, the LangGraph workflow, the API and the 3D twin all run end to end on synthetic
frames today, and the 12 tests pass. Nothing has been tried on real store footage yet, and
the CI workflow has not been run.

## The problem

A supermarket team cannot walk every aisle every hour. An empty facing on a fast mover, a
pack that a shopper put back in the wrong bay, a slot short of its planned facings or a
missing price tag each cost sales until somebody notices, and on-shelf availability is the
number store managers are measured on. Planogram audits that catch these are manual, done
with a clipboard, and weekly at best. The store already has cameras pointed at the shelves;
the footage is only watched after a theft.

## Why it is hard

Detecting a pack is not the hard part. The hard part is turning noisy per-frame detections
into decisions a merchandiser will trust: a shopper standing in front of a shelf hides
products for a frame or two and must not become an out-of-stock alert; a bay has to be
matched slot by slot against the planogram in the camera's own perspective; the fault has
to be confirmed before it costs a person a trip to the backroom; and when the evidence is
weak, the system has to say so and ask, not guess. Every task has to be explainable from a
frame, a slot and a rule.

## The approach

A **YOLOv8n** detector, fine-tuned on CPU in about 15 minutes on synthetic shelf frames, finds
product packs (by family), empty gaps, price tags and shoppers. Everything after that is
deterministic: boxes are mapped through the camera homography onto the bay plane and
assigned to planogram slots, a per-slot status is derived by counting, and a **temporal
tracker** confirms a fault only after three consecutive unoccluded frames agree. A
**LangGraph** supervisor runs four agents per frame:

| Agent | Decides | How |
|---|---|---|
| **Vision agent** | What is in the latest frame of each camera | Runs the detector |
| **Compliance agent** | ok / out of stock / misplaced / short facings / missing tag per slot; compliance and OSA | Slot geometry, counting, temporal confirmation |
| **Merchandising agent** | Which store tasks to raise, in what order | Restock, relocate, re-face or fix tag; priority = family velocity x task weight; weak evidence pauses for a reviewer |
| **Inventory agent** | Where the stock comes from | Backroom, else DC transfer, else a replenishment request in the agentic-supply-planning purchase-order format |

The key decision: **the detector classifies product families, not SKUs**. The planogram
already says which SKU belongs in each slot, so SKU identity comes from slot geometry; the
network only has to tell nine families, a gap, a tag and a shopper apart, which is what a
small model can do reliably at CCTV resolution. The cost, stated up front, is that a swap
between two SKUs of the same family is invisible. No language model is involved in any
decision; one may optionally write the shift briefing, and the workflow runs end to end
without it. The product universe is the RETAIL domain of
[agentic-supply-planning](https://github.com/kavya2693/agentic-supply-planning), so a replenishment request raised
here is a purchase order that project can plan.

```
supervisor ─► vision ─► compliance ─► merchandising ─► [reviewer] ─► inventory ─► done
     ▲__________|___________|______________|_______________|            (audit log: camera, frame, slot, SKU, task)
```

## The result

Synthetic data throughout: 45 SKUs, 90 slots, 6 fixed cameras, 16 frames per camera (one
every 30 s), 26 faults injected at known frames, shoppers passing for one or two frames.
Every number below is read from `outputs/metrics/detector.json` and
`outputs/metrics/pipeline.json` as produced by the shipped weights.

| Metric | Value |
|---|---|
| Detector mAP50 on the held-out synthetic test split | **0.976** (mAP50-95 0.924, precision 0.969, recall 0.949) |
| Weakest class | gap: AP50 0.874, AP50-95 0.611 |
| Training time, YOLOv8n, 30 epochs, 512 px, CPU (Apple M-series) | 877 s |
| Slot-status accuracy, raw per-frame / with smoothing | 94.2% / 94.9% |
| False-alert rate, raw / smoothed | 6.1% / **0.0%** |
| False-alert rate on slot-frames hidden behind a shopper, raw / smoothed | **91.0%** / 0.0% |
| Miss rate (fault present, no alert), raw / smoothed | 2.4% / **22.0%** |
| Faults detected within the sequence, raw / smoothed | 25 of 26 / 24 of 26 |
| Mean time-to-detect, raw / smoothed | 0.04 / 2.17 frames |
| End of sequence: compliance / on-shelf availability | 68.9% / 82.2% |

The two headline numbers disagree on purpose. Without smoothing almost every slot a
shopper stands in front of raises a false out-of-stock alert (91% of those slot-frames).
With smoothing there are none, but every fault is reported about two frames (one minute)
late and the miss rate rises roughly ninefold, because the frames before confirmation count as misses and
a fault that appears while a shopper is passing waits even longer.

The disappointing number is the smoothed miss rate. After smoothing, 25 of 111 misplaced
slot-frames, 20 of 72 short-facing slot-frames and 16 of 83 out-of-stock slot-frames are
still reported as fine, most of them the frames before a fault is confirmed. In the raw pass
5 misplaced slot-frames are read as fine, because the single foreign pack is assigned to a
neighbouring slot or detected as the expected family when its colour is close. One of the
26 injected faults is never detected raw and two are never confirmed after smoothing. The
confusion matrices are in `outputs/metrics/pipeline.json`.

## How it works

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full walk-through and
[docs/adr/0001](docs/adr/0001-family-level-detector-and-deterministic-compliance.md) for the
decisions.

Per frame the supervisor routes vision, compliance, merchandising and inventory in order.
Compliance keeps a tracker per slot in the graph state; a status change needs three
consecutive observed frames, and frames where a detected shopper box covers more than 35%
of the slot are skipped. Merchandising raises one task per newly confirmed fault on a slot
with no open task. A finding whose evidence is weaker than 0.55 (nothing detected where
stock should be and no gap box either, or fewer boxes than facings without a gap) is held
at a LangGraph `interrupt()` until a reviewer approves or rejects it; the twin resumes the
paused graph with each decision. Inventory reserves backroom units for issued restocks,
falls back to the DC, and otherwise raises a replenishment request. Every step is an audit
row with the camera, frame, slot, SKU and task.

## Running it

```bash
uv sync
uv run shelf-vision generate   # catalogue, planogram, 360 training images, 96 deployment frames + ground truth
uv run shelf-vision train      # YOLOv8n on CPU, ~15 min; writes data/models/shelf_vision.pt and outputs/metrics/detector.json
uv run shelf-vision detect     # cache the detector's boxes for the deployment frames
uv run shelf-vision eval       # status accuracy, false alerts, time-to-detect, raw vs smoothed
uv run shelf-vision run        # step the agents through all 16 frames; outputs/ holds tasks, requests, audit log, report
uv run shelf-vision all        # the whole chain
```

Trained weights are shipped in `data/models/shelf_vision.pt`, so `generate`, `detect`,
`eval` and `run` work without training. `shelf-vision run --interactive` asks for each
review at the prompt.

The 3D twin:

```bash
uv run shelf-vision-api                 # http://127.0.0.1:8020/api/state
cd twin && npm install && npm run dev   # http://localhost:5173, /api proxied to the backend
```

Click a camera for its latest frame with boxes, a slot for planogram-versus-detected and
its frame timeline, a task for its journey from frame to stock check, a pallet for backroom
stock, an agent station for its decisions. The review queue approves or rejects
weak-evidence findings; the clock steps frames.

## The data

Everything is generated by `src/shelf_vision/data.py` from one seed and is byte-identical
on re-run. A bay is drawn face-on (packs as shaped, coloured, labelled blocks; empty
facings show the shelf back; price tags on the rail), warped by a fixed per-camera
perspective, overlaid with shoppers and trolleys, then given lighting drift, vignette,
sensor noise and blur. Ground truth is exact because the boxes come from the drawing code.
The deployment sequences are rendered from a planogram the detector never saw.

Its limits are the project's biggest limitation: these are not CCTV frames. Real footage
has motion blur, compression, reflections, mixed lighting, packs at angles, labels the
camera cannot read and shelves far denser than fifteen slots. The mAP50 here says the
pipeline works on its own data, not that the detector would survive a real store.

## Tests

`uv run pytest -q` runs 12 tests without a model or an API key. The two that matter most:

- `test_slot_mapping_recovers_ground_truth_on_unoccluded_slots` replays ground-truth boxes
  through the geometry and asserts the derived status matches the truth on at least 97% of
  unoccluded slot-frames, so the homography and slot assignment are proven before the
  detector is involved.
- `test_smoothing_suppresses_transient_occlusion_but_confirms_persistent_faults` feeds a
  tracker two occluded out-of-stock frames and checks no alert is raised, then three clean
  ones and checks it is confirmed on the third and cleared the same way.

The rest cover generator determinism, compliance arithmetic, the graph running with no
LLM, the review interrupt pausing and resuming (all at once and one task at a time), task
priority and replenishment, and the API.

## Known limitations

- **Synthetic images only.** No real store data, no real CCTV; the domain gap is the
  biggest gap in this project and nothing here measures it.
- A misplaced pack of the same family as the slot's SKU is not detected.
- A foreign pack can be assigned to the neighbouring slot, so some misplacements read as
  fine even when the detector found the pack.
- Smoothing costs about two frames of latency and reports a 22% miss rate on slot-frames,
  most of it the confirmation delay.
- Facing counts come from box counting; overlapping or merged boxes under-count and are
  routed to review rather than resolved.
- Faults persist until the end of the sequence; nobody fixes a shelf, so tasks never close.
- One store, six bays, one fixed camera per bay with a known homography. Camera
  calibration is given, not estimated.

## Insights and learning

The oracle detector was worth building first. Replaying ground-truth boxes through the
geometry showed the slot assignment and status rules were right before any training, and
when the real detector disagreed with the truth the question was never "is the model too
weak" but "which rule is being handed the wrong thing". The misplacement misses came out of
that comparison: the geometry, not the detector, was at fault.

The smoothing result was expected in direction and surprising in size. 91% of the
slot-frames behind a shopper raise a false alert without it; that is the number that
justifies the whole temporal layer, and it also means a per-frame demo of this kind of
system is close to worthless.

What I got wrong first: the catalogue's stock draws shared the renderer's random stream,
so changing how many SKUs had no stock silently changed every image and invalidated the
trained model. Stock now has its own seed and the generator is tested for byte-identical
output.

Next: estimate the homography from the shelf edges instead of taking it from the
generator, hold detections at facing level for a second detector pass on the crop, and let
the twin close tasks when a later frame shows the slot restored.

## License

MIT
