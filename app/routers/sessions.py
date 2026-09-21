import json
import shutil
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DBSession

from app.database import get_db
from app.config import UPLOADS_DIR, DATA_DIR
from app.models import ScanSession, Observation
from app.schemas import SessionDetail, SessionSummary, ObservationOut, VerificationUpdate
from app.pipeline.orchestrator import run_pipeline, run_photo_pipeline

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _to_summary(session: ScanSession) -> SessionSummary:
    counts = Counter(o.label for o in session.observations)
    return SessionSummary(
        session_id=session.id,
        farm_id=session.farm_id,
        source_type=session.source_type,
        status=session.status,
        start_timestamp=session.start_timestamp,
        end_timestamp=session.end_timestamp,
        frames_extracted=session.frames_extracted,
        frames_used=session.frames_used,
        observation_counts=dict(counts),
        error_message=session.error_message,
    )


@router.post("/upload", response_model=SessionSummary)
async def upload_scan(
    background_tasks: BackgroundTasks,
    farm_id: str = Form(...),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    video: UploadFile = File(...),
    db: DBSession = Depends(get_db),
):
    """
    Farmer (or test script) uploads a video for a farm. A ScanSession is
    created immediately with status='uploaded'; the pipeline then runs as
    a background task and the session moves to 'processing' -> 'completed'
    or 'failed'. Poll GET /sessions/{session_id} for progress/results.
    """
    session = ScanSession(
        farm_id=farm_id,
        source_type="video",
        start_timestamp=datetime.now(timezone.utc),
        start_lat=lat,
        start_lon=lon,
        status="uploaded",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    dest_path = UPLOADS_DIR / f"{session.id}_{video.filename}"
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    session.source_video_path = str(dest_path)
    db.commit()

    background_tasks.add_task(_run_pipeline_task, session.id)

    return _to_summary(session)


@router.post("/upload-photo", response_model=SessionSummary)
async def upload_photo(
    background_tasks: BackgroundTasks,
    farm_id: str = Form(...),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    photo: UploadFile = File(...),
    db: DBSession = Depends(get_db),
):
    """
    Single-photo input. Treated as a one-frame scan through the same
    detector pipeline as video - no frame extraction/blur filtering, since
    the farmer already chose this one shot.
    """
    session = ScanSession(
        farm_id=farm_id,
        source_type="photo",
        start_timestamp=datetime.now(timezone.utc),
        start_lat=lat,
        start_lon=lon,
        status="uploaded",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    dest_path = UPLOADS_DIR / f"{session.id}_{photo.filename}"
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(photo.file, f)

    session.source_video_path = str(dest_path)
    db.commit()

    background_tasks.add_task(_run_photo_pipeline_task, session.id)

    return _to_summary(session)


@router.post("/upload-voice")
async def upload_voice():
    """
    Not implemented. Scaffolded in the schema (ScanSession.source_type
    already supports 'voice') so wiring in real speech-to-text later
    doesn't require a data model change - but this MVP does not fabricate
    transcription or detection from audio.
    """
    raise HTTPException(
        status_code=501,
        detail="Voice input is not implemented in this MVP. The schema supports it "
        "(source_type='voice') for when a speech-to-text step is built.",
    )


@router.post("/upload-document")
async def upload_document():
    """
    Not implemented - and deliberately not attempted without a defined scope
    for what 'document' means here (a soil test report? a field note?).
    Scaffolded in the schema for when that's defined.
    """
    raise HTTPException(
        status_code=501,
        detail="Document input is not implemented in this MVP. The schema supports it "
        "(source_type='document') for when document parsing scope is defined.",
    )


def _run_pipeline_task(session_id: str):
    # Runs in a background task with its own DB session, since the request-scoped
    # session from the endpoint is closed by the time this executes.
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        session = db.query(ScanSession).filter(ScanSession.id == session_id).first()
        if session:
            run_pipeline(db, session)
    finally:
        db.close()


def _run_photo_pipeline_task(session_id: str):
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        session = db.query(ScanSession).filter(ScanSession.id == session_id).first()
        if session:
            run_photo_pipeline(db, session)
    finally:
        db.close()


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: str, db: DBSession = Depends(get_db)):
    session = db.query(ScanSession).filter(ScanSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    summary = _to_summary(session)
    observations = []
    for o in session.observations:
        soft_signal = False
        if o.raw_model_output:
            try:
                soft_signal = json.loads(o.raw_model_output).get("soft_signal", False)
            except (json.JSONDecodeError, AttributeError):
                pass
        observations.append(
            ObservationOut(
                id=o.id,
                label=o.label,
                confidence=o.confidence,
                timestamp=o.timestamp,
                lat=o.lat,
                lon=o.lon,
                detector_name=o.detector_name,
                detector_version=o.detector_version,
                evidence_image_url=f"/sessions/{session_id}/observations/{o.id}/image",
                soft_signal=soft_signal,
                verification_status=o.verification_status,
            )
        )
    return SessionDetail(**summary.model_dump(), observations=observations)


@router.get("/{session_id}/observations/{observation_id}/image")
def get_evidence_image(session_id: str, observation_id: str, db: DBSession = Depends(get_db)):
    obs = (
        db.query(Observation)
        .filter(Observation.id == observation_id, Observation.session_id == session_id)
        .first()
    )
    if not obs:
        raise HTTPException(status_code=404, detail="Observation not found")

    # Resolve against DATA_DIR, not BASE_DIR - evidence_image_path is stored
    # relative to wherever EVIDENCE_DIR actually lives (see app/config.py),
    # which differs from the code directory on hosts like Render where
    # DATA_DIR points at a mounted persistent disk.
    image_path = DATA_DIR / obs.evidence_image_path
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Evidence image file missing on disk")

    return FileResponse(str(image_path))


@router.patch("/{session_id}/observations/{observation_id}/verify", response_model=ObservationOut)
def verify_observation(
    session_id: str,
    observation_id: str,
    update: VerificationUpdate,
    db: DBSession = Depends(get_db),
):
    """
    Human verification, backend-only for now (no review UI yet). Sets an
    observation's verification_status to 'verified' or 'rejected'.
    """
    obs = (
        db.query(Observation)
        .filter(Observation.id == observation_id, Observation.session_id == session_id)
        .first()
    )
    if not obs:
        raise HTTPException(status_code=404, detail="Observation not found")
    if update.status not in ("pending", "verified", "rejected"):
        raise HTTPException(status_code=400, detail="status must be pending, verified, or rejected")

    obs.verification_status = update.status
    db.commit()
    db.refresh(obs)

    soft_signal = False
    if obs.raw_model_output:
        try:
            soft_signal = json.loads(obs.raw_model_output).get("soft_signal", False)
        except (json.JSONDecodeError, AttributeError):
            pass

    return ObservationOut(
        id=obs.id,
        label=obs.label,
        confidence=obs.confidence,
        timestamp=obs.timestamp,
        lat=obs.lat,
        lon=obs.lon,
        detector_name=obs.detector_name,
        detector_version=obs.detector_version,
        evidence_image_url=f"/sessions/{session_id}/observations/{obs.id}/image",
        soft_signal=soft_signal,
        verification_status=obs.verification_status,
    )


@router.get("", response_model=list[SessionSummary])
def list_sessions(farm_id: str | None = None, db: DBSession = Depends(get_db)):
    query = db.query(ScanSession)
    if farm_id:
        query = query.filter(ScanSession.farm_id == farm_id)
    sessions = query.order_by(ScanSession.start_timestamp.desc()).all()
    return [_to_summary(s) for s in sessions]

