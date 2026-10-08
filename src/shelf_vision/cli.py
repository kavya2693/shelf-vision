"""Command line entry points.

shelf-vision generate     # catalogue, planogram, training set, deployment sequences + ground truth
shelf-vision train        # fine-tune YOLOv8n on CPU, evaluate on the held-out test split
shelf-vision detect       # run the detector over every deployment frame and cache the boxes
shelf-vision eval         # compliance accuracy, false alerts and time-to-detect, with and without smoothing
shelf-vision run          # step the twin through every frame with the agents; write outputs/
shelf-vision all          # the whole chain
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import EPOCHS, OUT


def main() -> None:
    ap = argparse.ArgumentParser(prog="shelf-vision")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate")
    tr = sub.add_parser("train")
    tr.add_argument("--epochs", type=int, default=EPOCHS)
    det = sub.add_parser("detect")
    det.add_argument("--oracle", action="store_true", help="replay ground truth instead of the model")
    sub.add_parser("eval")
    run = sub.add_parser("run")
    run.add_argument("--interactive", action="store_true", help="answer review questions at the prompt")
    al = sub.add_parser("all")
    al.add_argument("--epochs", type=int, default=EPOCHS)
    args = ap.parse_args()

    if args.cmd in ("generate", "all"):
        from .data import generate

        print("generated", json.dumps(generate()))
    if args.cmd in ("train", "all"):
        from .detector import train

        m = train(epochs=args.epochs)
        print(f"detector mAP50 {m['map50']:.3f} (mAP50-95 {m['map50_95']:.3f}) in {m['train_seconds']} s")
        for k, v in m["per_class"].items():
            print(f"  {k:14} AP50 {v['ap50']:.3f}")
    if args.cmd in ("detect", "all"):
        from .pipeline import cache_detections

        s = cache_detections(oracle=getattr(args, "oracle", False))
        print(f"cached {s['frames']} frames, {s['detections']} detections with {s['detector']}")
    if args.cmd in ("eval", "all"):
        from .evaluate import evaluate_pipeline

        m = evaluate_pipeline()
        print(json.dumps(m, indent=1))
    if args.cmd in ("run", "all"):
        from .twin import run_all

        rep = run_all(interactive=getattr(args, "interactive", False))
        print(rep)
        print(f"outputs written to {OUT}")
    sys.exit(0)
