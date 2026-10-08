"""Shared constants. Every number the agents act on lives here, so a store manager can change
policy without touching agent code."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = ROOT / "outputs"
MODELS = DATA / "models"
METRICS = OUT / "metrics"

SEED = 7

# Store layout: one store, three aisles, one bay per aisle side, one fixed camera per bay.
N_AISLES = 3
SIDES = ("L", "R")
SHELVES_PER_BAY = 3
SLOTS_PER_SHELF = 5
BAY_WIDTH_MM = 1250
SHELF_PITCH_MM = 320  # vertical distance between shelf boards
SHELF_BOARD_MM = 30  # thickness of the board, which carries the price-tag rail

# Rendering
IMG_W, IMG_H = 512, 384
N_FRAMES = 16  # frames per camera in the deployment sequence the twin steps through
FRAME_SECONDS = 30  # a frame every 30 s, so 16 frames is an 8-minute window

# Training set (random bays, random faults, random occluders)
TRAIN_IMAGES = 240
VAL_IMAGES = 60
TEST_IMAGES = 60

# Detector
IMGSZ = 512
EPOCHS = 30
CONF_THRESHOLD = 0.25
REVIEW_CONFIDENCE = 0.55  # slot findings whose evidence is weaker than this wait for a person

# Temporal smoothing: a fault has to be seen this many consecutive, unoccluded frames
PERSIST_FRAMES = 3
OCCLUDED_FRACTION = 0.35  # a slot this covered by a shopper box is "not observed"

# Merchandising: units moved per restock, priority weights per task type
UNITS_PER_FACING = 2
TASK_WEIGHT = {"restock": 1.0, "relocate": 0.7, "reface": 0.5, "fix_tag": 0.3}
