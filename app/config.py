"""
Central configuration for the Farm Observation MVP.

DETECTOR_REGISTRY_CONFIG is the important part: it's the list of detectors
the pipeline will run on every frame. To add a new observation capability
later (e.g. a scientifically validated pest/disease model), you add a new
entry here and implement the corresponding Detector class in
app/detectors/. You do NOT need to touch the pipeline orchestrator.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Storage paths ---
# DATA_DIR is where persistent state (evidence images, uploaded videos, the
# SQLite DB) actually lives. Defaults to the project folder for local dev.
# On a host with an ephemeral filesystem (Render, most PaaS free/standard
# tiers), set DATA_DIR to a mounted persistent disk path via env var, or
# this data is silently wiped on every redeploy/restart.
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
EVIDENCE_DIR = DATA_DIR / "evidence"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "farm_observations.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# --- Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# --- Frame extraction ---
FRAME_SAMPLE_INTERVAL_SECONDS = float(os.getenv("FRAME_SAMPLE_INTERVAL_SECONDS", 1.0))
BLUR_THRESHOLD = float(os.getenv("BLUR_THRESHOLD", 80.0))  # Laplacian variance
MAX_FRAMES_PER_SESSION = int(os.getenv("MAX_FRAMES_PER_SESSION", 5))  # safety cap

# --- Confidence ---
DEFAULT_CONFIDENCE_THRESHOLD = float(os.getenv("DEFAULT_CONFIDENCE_THRESHOLD", 0.5))

# --- Detector registry ---
# Each entry describes one detector instance the pipeline will run.
# "class" refers to a key in app/detectors/registry.py:DETECTOR_CLASSES
#
# To add a new (e.g. scientifically validated) detector later:
#   1. Implement a new class in app/detectors/ that subclasses Detector
#   2. Register it in DETECTOR_CLASSES in app/detectors/registry.py
#   3. Add a config entry below
# The pipeline itself never changes.
DETECTOR_REGISTRY_CONFIG = [
    {
        "class": "GeminiDetector",
        "enabled": True,
        "name": "gemini_vegetation_zero_shot",
        "version": "1.0",
        "confidence_threshold": DEFAULT_CONFIDENCE_THRESHOLD,
        "params": {
            "labels": [
                "ground_soil_cover",
                "bare_soil",
                "vegetation_diversity",
                "tree_canopy_presence",
                "visible_biodiversity",
                "surface_water_erosion_evidence",
            ]
        },
    },
    # Example of a future entry (not active yet):
    # {
    #     "class": "ValidatedDiseaseDetector",
    #     "enabled": False,
    #     "name": "cassava_mosaic_v1",
    #     "version": "1.0",
    #     "confidence_threshold": 0.6,
    #     "params": {"model_path": "models/cassava_mosaic_v1.pt"},
    # },
]
