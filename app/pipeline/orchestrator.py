"""
The pipeline orchestrator. This is intentionally "dumb": it extracts
frames, loops every registered detector over every frame, and persists
whatever comes back above threshold as an Observation. It has zero
knowledge of what "plant_or_tree" or "bare_soil" mean - that logic lives
entirely inside detectors. This is what makes it possible to add new
observation types without ever touching this file.

A single photo is treated as a one-frame scan and shares the exact same
_process_frames() core as video - the only difference is how the frame(s)
get produced (extract_frames() for video, a direct cv2.imread() for a
photo). This means adding voice/document input later means writing a
function that produces frames (e.g. from an image referenced in a
document) and calling the same core, not duplicating detector logic.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import cv2
from sqlalchemy.orm import Session as DBSession

from app.models import ScanSession, Observation
from app.pipeline.frame_extraction import extract_frames, ExtractedFrame
from app.detectors.registry import build_active_detectors
from app.storage import save_evidence_image

logger = logging.getLogger(__name__)


def _process_frames(db: DBSession, session: ScanSession, frames: list[ExtractedFrame]) -> None:
    """Shared core: runs every active detector on every frame, persists Observations."""
    detectors = build_active_detectors()
    base_time = session.start_timestamp or datetime.now(timezone.utc)

    for extracted in frames:
        frame_timestamp = base_time + timedelta(seconds=extracted.offset_seconds)
        # MVP: single GPS fix for the whole session. If a GPS trail is
        # supplied in the future, interpolate per-frame here instead -
        # this is the only place that decision needs to be made.
        lat = session.start_lat
        lon = session.start_lon

        for detector in detectors:
            detections = detector.run(extracted.frame)
            for det in detections:
                if det.confidence < detector.confidence_threshold:
                    continue

                observation = Observation(
                    session_id=session.id,
                    farm_id=session.farm_id,
                    timestamp=frame_timestamp,
                    lat=lat,
                    lon=lon,
                    label=det.label,
                    confidence=det.confidence,
                    detector_name=detector.name,
                    detector_version=detector.version,
                    bbox_json=json.dumps(det.bbox) if det.bbox else None,
                    evidence_image_path="",  # set below once we have the id
                    raw_model_output=json.dumps(det.raw_output),
                )
                db.add(observation)
                db.flush()  # assigns observation.id without full commit

                observation.evidence_image_path = save_evidence_image(
                    extracted.frame, session.farm_id, session.id, observation.id
                )
                db.add(observation)

    # Surface detector failures instead of letting them hide behind a silent
    # "0 observations" result. A detector that failed on every frame looks
    # identical to "nothing was there" unless this is checked explicitly.
    warnings = []
    for detector in detectors:
        error_count = getattr(detector, "error_count", 0)
        if error_count > 0:
            attempted = getattr(detector, "frames_attempted", 0)
            last_error = getattr(detector, "last_error", "unknown error")
            warnings.append(
                f"{detector.name} failed on {error_count}/{attempted} frames "
                f"(last error: {last_error})"
            )
    if warnings:
        session.error_message = "; ".join(warnings)
        db.commit()


def run_pipeline(db: DBSession, session: ScanSession) -> None:
    """
    Runs the full pipeline for a video ScanSession that already has a
    source_video_path set, and writes Observation rows directly to the DB.
    Mutates `session.status` to reflect progress/outcome.
    """
    session.status = "processing"
    db.commit()

    try:
        usable_frames, total_sampled = extract_frames(session.source_video_path)

        session.frames_extracted = total_sampled
        session.frames_used = len(usable_frames)
        db.commit()

        if not usable_frames:
            session.status = "failed"
            session.error_message = "No usable frames survived extraction/quality filtering."
            db.commit()
            return

        _process_frames(db, session, usable_frames)

        session.status = "completed"
        session.end_timestamp = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        logger.exception("Pipeline failed for session %s", session.id)
        session.status = "failed"
        session.error_message = str(exc)
        db.commit()


def run_photo_pipeline(db: DBSession, session: ScanSession) -> None:
    """
    Runs the pipeline for a single-photo ScanSession. A photo is treated as
    a one-frame scan: no sampling/blur filtering (the farmer already chose
    this one shot), same detector loop as video.
    """
    session.status = "processing"
    db.commit()

    try:
        frame = cv2.imread(session.source_video_path)
        if frame is None:
            session.status = "failed"
            session.error_message = "Could not read the uploaded photo file."
            db.commit()
            return

        session.frames_extracted = 1
        session.frames_used = 1
        db.commit()

        single_frame = ExtractedFrame(frame=frame, offset_seconds=0.0, sharpness=0.0)
        _process_frames(db, session, [single_frame])

        session.status = "completed"
        session.end_timestamp = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        logger.exception("Photo pipeline failed for session %s", session.id)
        session.status = "failed"
        session.error_message = str(exc)
        db.commit()
