import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Text, Integer
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class ScanSession(Base):
    """One camera scan of a farm. Created when a farmer starts a scan."""

    __tablename__ = "scan_sessions"

    id = Column(String, primary_key=True, default=_uuid)
    farm_id = Column(String, nullable=False, index=True)

    # video | photo | voice | document — voice/document are scaffolded in the
    # schema but not yet processed (see app/routers/sessions.py). Keeping this
    # field now means adding real voice/document processing later doesn't
    # require a schema migration.
    source_type = Column(String, default="video", nullable=False)

    start_timestamp = Column(DateTime, default=_now, nullable=False)
    end_timestamp = Column(DateTime, nullable=True)

    # GPS is captured at session start at minimum. If a GPS trail is provided
    # (live browser geolocation), individual observations may carry their own
    # more precise coordinates; this is the session-level fallback.
    start_lat = Column(Float, nullable=True)
    start_lon = Column(Float, nullable=True)

    # uploaded | processing | completed | failed
    status = Column(String, default="uploaded", nullable=False)
    source_video_path = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

    frames_extracted = Column(Integer, default=0)
    frames_used = Column(Integer, default=0)  # after blur/quality filtering

    observations = relationship(
        "Observation", back_populates="session", cascade="all, delete-orphan"
    )


class Observation(Base):
    """
    One structured observation produced by one detector on one frame.
    Every field required by the MVP spec (evidence image, timestamp, GPS,
    farm ID, confidence) is mandatory at the schema level.
    """

    __tablename__ = "observations"

    id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, ForeignKey("scan_sessions.id"), nullable=False)
    farm_id = Column(String, nullable=False, index=True)

    timestamp = Column(DateTime, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)

    label = Column(String, nullable=False, index=True)
    confidence = Column(Float, nullable=False)

    detector_name = Column(String, nullable=False)
    detector_version = Column(String, nullable=False)

    bbox_json = Column(Text, nullable=True)  # JSON-encoded [y0,x0,y1,x1] normalized 0-1000
    evidence_image_path = Column(String, nullable=False)
    raw_model_output = Column(Text, nullable=True)  # JSON-encoded, kept for future reprocessing

    # pending | verified | rejected — set by a human reviewer. No review UI
    # exists yet; this is the flag + API for one to be built against later.
    verification_status = Column(String, default="pending", nullable=False)

    session = relationship("ScanSession", back_populates="observations")
