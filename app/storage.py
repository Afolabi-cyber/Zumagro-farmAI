"""Handles saving evidence images to disk in a predictable, farm/session-scoped layout."""

import cv2
import numpy as np

from app.config import EVIDENCE_DIR


def save_evidence_image(frame: np.ndarray, farm_id: str, session_id: str, observation_id: str) -> str:
    """
    Saves the frame as JPEG evidence and returns the path (relative to
    EVIDENCE_DIR's parent, i.e. usable for building a URL) where it was stored.
    """
    session_dir = EVIDENCE_DIR / farm_id / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{observation_id}.jpg"
    full_path = session_dir / filename
    cv2.imwrite(str(full_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])

    # Return a path relative to the project root, stored in DB, used to build the serving URL
    return f"evidence/{farm_id}/{session_id}/{filename}"
