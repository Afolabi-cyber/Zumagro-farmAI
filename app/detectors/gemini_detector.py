"""
Zero-shot vegetation/ground detector backed by the Gemini API.

This is a PLACEHOLDER detector by design. It is not a scientifically
validated agronomy model - it's a general-purpose vision-language model
being asked to point at plants, bare soil, ground cover, and flowers/fruit.
It exists to prove the pipeline works end-to-end. The confidence score it
returns is the model's own self-reported estimate (a heuristic), not a
calibrated statistical probability - this distinction is preserved in the
stored records (detector_name makes the source explicit) so nobody
downstream mistakes a zero-shot guess for a validated finding.

When a scientifically validated model becomes available for any of these
labels, implement it as a new Detector subclass and register it in
registry.py / config.py. This class does not need to change.
"""

import json
import logging
from io import BytesIO

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY, GEMINI_MODEL
from app.detectors.base import Detector, Detection

logger = logging.getLogger(__name__)


class _BoxOut(BaseModel):
    box_2d: list[int] = Field(
        description="Bounding box as [ymin, xmin, ymax, xmax], normalized 0-1000"
    )
    label: str = Field(description="One of the requested labels")
    confidence: float = Field(
        description="Model's own confidence estimate for this detection, 0.0 to 1.0"
    )


class _DetectionOut(BaseModel):
    detections: list[_BoxOut]


# Passed to Gemini's response_schema as a flat dict, NOT as the _DetectionOut
# pydantic class directly. Passing a pydantic model with a nested model inside
# it (list[_BoxOut] here) makes Pydantic generate $ref/$defs for the nested
# type, and the google-genai SDK's own schema validation rejects that shape
# client-side before the request is even sent (a known SDK bug - see
# googleapis/python-genai issue #60). This flat, fully-inlined schema
# sidesteps it entirely. _BoxOut/_DetectionOut above are still used to
# validate the response we get back, just not to build the request schema.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "detections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "box_2d": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "[ymin, xmin, ymax, xmax], normalized 0-1000",
                    },
                    "label": {"type": "string", "description": "One of the requested labels"},
                    "confidence": {
                        "type": "number",
                        "description": "Model's own confidence estimate, 0.0 to 1.0",
                    },
                },
                "required": ["box_2d", "label", "confidence"],
            },
        }
    },
    "required": ["detections"],
}


class GeminiDetector(Detector):
    def __init__(self, name: str, version: str, confidence_threshold: float, labels: list[str]):
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        self.name = name
        self.version = version
        self.confidence_threshold = confidence_threshold
        self.labels = labels
        self._client = genai.Client(api_key=GEMINI_API_KEY)
        # Tracked so the orchestrator can tell a real API failure apart from
        # a frame that legitimately had nothing to detect - previously a
        # failed call just returned [] silently, which looked identical to
        # "nothing found" on the results page. That's the bug: a 0-observation
        # result gave no way to tell which one happened.
        self.error_count = 0
        self.frames_attempted = 0
        self.last_error: str | None = None

    # Labels where a single still frame is a fundamentally weaker signal than
    # for the others (judgment-over-the-whole-frame or small/moving subjects,
    # rather than a single clear object). Kept in the same pipeline/schema,
    # but the frontend visually flags these so a farmer or agronomist doesn't
    # read them with the same confidence as e.g. bare_soil.
    SOFT_SIGNAL_LABELS = {"vegetation_diversity", "visible_biodiversity"}

    def _build_prompt(self) -> str:
        label_list = ", ".join(self.labels)
        return (
            f"You are analyzing a single still frame extracted from a farm field-scan video. "
            f"Detect all instances of the following categories, if present: {label_list}.\n\n"
            f"Definitions:\n"
            f"- ground_soil_cover: ground covered by low vegetation, mulch, or crop residue "
            f"(i.e. NOT exposed bare soil)\n"
            f"- bare_soil: patches of exposed, uncovered soil/ground with no vegetation or cover\n"
            f"- vegetation_diversity: evidence of multiple distinct plant or crop types/species "
            f"visible together in this frame (not just one uniform crop)\n"
            f"- tree_canopy_presence: any visible tree, shrub, or canopy structure\n"
            f"- visible_biodiversity: any visible fauna - insects, birds, or other wildlife - "
            f"in the frame\n"
            f"- surface_water_erosion_evidence: visible standing or flowing water, OR visible "
            f"erosion features such as gullies, rills, or exposed plant roots from soil loss\n\n"
            f"For each detected instance, return a bounding box in the format "
            f"[ymin, xmin, ymax, xmax] normalized to a 0-1000 scale, the matching label "
            f"(must be exactly one of: {label_list}), and your own confidence estimate "
            f"from 0.0 to 1.0 for that specific detection. "
            f"For vegetation_diversity and visible_biodiversity specifically: these are harder "
            f"to judge from a single still frame, so be conservative - only report them when "
            f"you can clearly justify the detection from what's actually visible. "
            f"Only report detections you can actually see in the image. "
            f"If nothing relevant is visible, return an empty list."
        )

    def run(self, frame: np.ndarray) -> list[Detection]:
        self.frames_attempted += 1

        # Convert BGR (OpenCV) -> RGB (PIL) for the API
        rgb = frame[:, :, ::-1]
        image = Image.fromarray(rgb)
        buf = BytesIO()
        image.save(buf, format="JPEG", quality=90)
        image_bytes = buf.getvalue()

        try:
            response = self._client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    self._build_prompt(),
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,
                    temperature=0.2,
                ),
            )
            # response.parsed only auto-populates when response_schema is a
            # pydantic class, which we deliberately don't use here (see the
            # comment on _RESPONSE_SCHEMA above) - so this always goes
            # through the manual JSON parse + pydantic validation path.
            parsed = _DetectionOut.model_validate_json(response.text)
        except Exception as exc:
            self.error_count += 1
            self.last_error = str(exc)
            logger.warning("Gemini detection call failed on a frame: %s", exc)
            return []

        detections = []
        for box in parsed.detections:
            if box.label not in self.labels:
                # Model hallucinated a label outside our taxonomy - skip it
                continue
            detections.append(
                Detection(
                    label=box.label,
                    confidence=max(0.0, min(1.0, box.confidence)),
                    bbox=box.box_2d,
                    raw_output={
                        "source": "gemini",
                        "model": GEMINI_MODEL,
                        "box": box.model_dump(),
                        "soft_signal": box.label in self.SOFT_SIGNAL_LABELS,
                    },
                )
            )
        return detections