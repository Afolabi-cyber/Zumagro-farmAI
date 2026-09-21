"""
Builds the list of active Detector instances from DETECTOR_REGISTRY_CONFIG.

This is the ONLY place that maps a config "class" string to an actual
Python class. To add a new detector type, add it to DETECTOR_CLASSES here
and add a corresponding entry in app/config.py. Nothing else in the
pipeline needs to know detectors exist as individual classes.
"""

from app.config import DETECTOR_REGISTRY_CONFIG
from app.detectors.base import Detector
from app.detectors.gemini_detector import GeminiDetector

DETECTOR_CLASSES = {
    "GeminiDetector": GeminiDetector,
    # "ValidatedDiseaseDetector": ValidatedDiseaseDetector,  # add future detectors here
}


def build_active_detectors() -> list[Detector]:
    detectors = []
    for entry in DETECTOR_REGISTRY_CONFIG:
        if not entry.get("enabled", False):
            continue
        cls = DETECTOR_CLASSES.get(entry["class"])
        if cls is None:
            raise ValueError(f"Unknown detector class in config: {entry['class']}")
        instance = cls(
            name=entry["name"],
            version=entry["version"],
            confidence_threshold=entry["confidence_threshold"],
            **entry.get("params", {}),
        )
        detectors.append(instance)
    if not detectors:
        raise RuntimeError("No detectors are enabled in DETECTOR_REGISTRY_CONFIG.")
    return detectors
