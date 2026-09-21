"""
Detector interface.

This is the contract that makes the pipeline modular. Every detector -
whether it's today's zero-shot Gemini detector or a future scientifically
validated model - implements this same interface. The pipeline orchestrator
only ever talks to detectors through this interface, so swapping or adding
detectors never requires touching pipeline code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
import numpy as np


@dataclass
class Detection:
    """One raw detection produced by a detector on a single frame."""

    label: str
    confidence: float  # 0.0 - 1.0
    bbox: list[int] | None = None  # [y0, x0, y1, x1] normalized 0-1000, or None
    raw_output: dict[str, Any] = field(default_factory=dict)


class Detector(ABC):
    """
    Base class for all detectors.

    name/version are stamped onto every Observation record so it's always
    traceable which model produced which finding - critical once multiple
    detector versions exist over time.
    """

    name: str
    version: str
    confidence_threshold: float = 0.5

    @abstractmethod
    def run(self, frame: np.ndarray) -> list[Detection]:
        """
        Run detection on a single frame (BGR numpy array, as read by OpenCV).
        Must return a list of Detection objects. Detections below
        self.confidence_threshold should still be returned; the pipeline
        (not the detector) is responsible for filtering, so thresholds stay
        configurable in one place.
        """
        raise NotImplementedError
