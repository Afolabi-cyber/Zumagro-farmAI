import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import sessions
from app.config import EVIDENCE_DIR

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Farm Observation MVP",
    description="Camera scan -> frames -> AI detection -> structured, evidence-backed observations.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


app.include_router(sessions.router)


@app.get("/api/status")
def api_status():
    return {"status": "ok", "message": "Farm Observation MVP API. UI is served at /."}


# Serve evidence images (must be registered before the root static mount below,
# since Starlette matches routes/mounts in the order they were added)
app.mount("/evidence", StaticFiles(directory=str(EVIDENCE_DIR)), name="evidence")

# Serve the capture/results web pages at the root, so the app itself opens at "/"
app.mount("/", StaticFiles(directory="static", html=True), name="static")
