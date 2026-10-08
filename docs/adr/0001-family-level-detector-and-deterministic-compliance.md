# ADR 0001: family-level detector, deterministic compliance, model only for the briefing

Status: accepted

## Context

The system has to turn CCTV frames into store tasks a merchandiser will act on. Three
decisions shape everything downstream: what the detector's classes are, where the slot
status is decided, and what a language model is allowed to do.

## Decision

1. **The detector classifies product families, not SKUs.** Nine family classes (the RETAIL
   domain of agentic-supply-planning), plus `gap` (shelf back where stock should be),
   `price_tag` and `shopper`. Which SKU belongs at a slot is already written in the
   planogram, so SKU identity is resolved by slot geometry: a family-level box inside the
   slot that expects that family is the expected SKU; a box of another family is a
   misplacement. At CCTV resolution colour and pack shape are what a small network can tell
   apart reliably; label text is not legible, and 45 SKU classes would need far more data
   than 240 training images to separate.

2. **Slot status is computed by deterministic geometry and counting.** Detections are mapped
   through the camera homography onto the bay plane, assigned to the slot they overlap most,
   and counted against the planogram. A tracker confirms a status only after three
   consecutive unoccluded frames agree. No model is asked whether a shelf looks compliant.

3. **A language model, if one is configured, only writes the shift briefing** and is told
   not to change any number. The workflow runs end to end with no model at all; the tests
   assert this.

## Consequences

- A swap between two SKUs of the same family is invisible to the system. This is listed as
  a limitation in the README rather than hidden.
- Findings that rest on an absence (no gap box and no product box, or fewer boxes than
  facings with no gap seen) carry weak evidence and are routed to a human reviewer through a
  LangGraph interrupt, instead of being issued as tasks.
- Every task is reproducible from the planogram, the detection cache and the config
  constants, and is logged with the camera, frame, slot and SKU that produced it.

## Rejected

- SKU-level classes: more classes than the data supports, and a real deployment would
  still need the planogram to say what belongs where.
- Asking a vision-language model to describe each shelf: not reproducible, not auditable,
  and the project has no API budget.
- Pure per-frame alerts: cheap, but 89% of the slot-frames hidden behind a shopper raise a
  false out-of-stock alert without temporal confirmation (measured, see README).
