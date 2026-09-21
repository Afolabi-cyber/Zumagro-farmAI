from datetime import datetime
from pydantic import BaseModel


class ObservationOut(BaseModel):
    id: str
    label: str
    confidence: float
    timestamp: datetime
    lat: float | None
    lon: float | None
    detector_name: str
    detector_version: str
    evidence_image_url: str
    soft_signal: bool = False
    verification_status: str = "pending"

    class Config:
        from_attributes = True


class SessionSummary(BaseModel):
    session_id: str
    farm_id: str
    source_type: str
    status: str
    start_timestamp: datetime
    end_timestamp: datetime | None
    frames_extracted: int
    frames_used: int
    observation_counts: dict[str, int]
    error_message: str | None


class SessionDetail(SessionSummary):
    observations: list[ObservationOut]


class VerificationUpdate(BaseModel):
    status: str  # "pending" | "verified" | "rejected"
