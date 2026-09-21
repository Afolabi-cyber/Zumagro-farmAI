# Farm Observation MVP

A technical demonstration of the core pipeline: **camera scan → frame extraction →
AI detection → structured, evidence-backed observation records.**

This is deliberately *not* an advisory system. It does not tell a farmer what to do.
It proves that a video scan of a farm can be turned into structured, traceable
observations — each with an evidence photo, timestamp, GPS, farm ID, and confidence
score — on an architecture where new (scientifically validated) detection models can
be added later without rebuilding the pipeline.

## What it does

1. Farmer opens the web app on their phone, enters a Farm ID, enables the camera,
   and records a short scan while walking the field.
2. The video uploads to the backend.
3. The backend samples still frames from the video (1/sec by default), discards
   blurry ones, and runs every **registered detector** on every surviving frame.
4. Right now there is one detector: a zero-shot Gemini-based detector covering six
   indicators — `ground_soil_cover`, `bare_soil`, `vegetation_diversity`,
   `tree_canopy_presence`, `visible_biodiversity`, `surface_water_erosion_evidence`.
   Two of these (`vegetation_diversity`, `visible_biodiversity`) are judgment calls
   about the whole frame rather than a single clear object, so they're flagged as
   `soft_signal: true` in every record and marked "SOFT SIGNAL" in the results UI —
   treat those two as a rough signal, not a firm reading.
5. Every detection above its confidence threshold becomes an **Observation** record:
   evidence image, timestamp, GPS, farm ID, label, confidence, and which
   detector/version produced it — all stored in SQLite.
6. The farmer is redirected to a results page showing a photo grid of every
   observation, grouped counts, and GPS links.

## Setup

```bash
cd farm-mvp
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and paste in your real GEMINI_API_KEY

uvicorn app.main:app --reload
```

Then open:
- **Capture app**: http://127.0.0.1:8000/ (use this on your phone — on the same
  wifi network, with your machine's LAN IP instead of 127.0.0.1 — since camera
  access requires either `localhost` or HTTPS)
- **API docs**: http://127.0.0.1:8000/docs
- **API status check**: http://127.0.0.1:8000/api/status

## Testing with your own sample videos

You don't need the browser to test the pipeline. Drop a video into `test_videos/`
and run:

```bash
python scripts/test_upload.py test_videos/your_video.mp4 --farm-id ZUMAGRO-FARM-014 --lat 6.5244 --lon 3.3792
```

This uploads the video, polls until processing finishes, and prints a summary plus
a link to the visual report. The server must already be running (`uvicorn app.main:app`).

If you don't have GPS coordinates for a video, you can omit `--lat`/`--lon` — the
observations will simply be stored with `lat`/`lon` as null, and it'll be visibly
obvious in the results page rather than silently faked.

## What "pass" looks like

- Run 2-3 representative farm videos through the pipeline.
- Confirm frames get extracted and blurry ones are correctly discarded
  (`frames_extracted` vs `frames_used` in the session summary).
- Confirm each observation has: a viewable evidence image, a label that matches
  what's actually in that frame, a timestamp, GPS (if provided), farm ID, and a
  confidence score.
- Confirm the results page renders correctly and evidence photos load.

If detections look wrong or too sparse/noisy, the two easiest knobs to turn first
are `DEFAULT_CONFIDENCE_THRESHOLD` and `BLUR_THRESHOLD` in `.env` — see comments
in `.env.example`.

## Input types

The pipeline supports two working input types and two scaffolded-but-not-implemented ones:

- **Video** (`/sessions/upload`) — implemented. Frame extraction + blur filtering + detection.
- **Photo** (`/sessions/upload-photo`) — implemented. Treated as a one-frame scan through
  the exact same detector loop as video (no sampling/filtering needed for a single shot).
- **Voice** (`/sessions/upload-voice`) — **not implemented**. Returns HTTP 501. The
  `ScanSession.source_type` field already supports `"voice"` so adding real
  speech-to-text later doesn't require a schema change, but this MVP does not
  fabricate transcription or detection from audio it can't actually process.
- **Document** (`/sessions/upload-document`) — **not implemented**, for the same
  reason, and also because "document" needs a defined scope before it's worth
  building (a soil test PDF is a very different parsing problem than a handwritten
  field note).

## Human verification

`Observation.verification_status` (`pending` / `verified` / `rejected`) exists and
is settable via `PATCH /sessions/{session_id}/observations/{observation_id}/verify`.
There is no review UI yet — this is backend-only, a flag and an API to build a
review workflow against later, not a finished feature.

## What this MVP deliberately does NOT do

The Crop / Soil / Management → "Farm Intelligence" layer (turning observations into
recommendations) is **out of scope for this MVP by design**. This system produces
confidence-scored, evidence-backed observations — it does not advise a farmer on
what to do about them. That's a distinct, higher-stakes system that should be built
(and validated) separately, once the observation layer itself is proven.

## Known limitations (by design, for this MVP)

- **Gemini's confidence score is the model's own self-reported estimate**, not a
  calibrated statistical probability. This is explicitly noted in
  `app/detectors/gemini_detector.py` and stamped into every record via
  `detector_name`, so it's always traceable which findings came from a zero-shot
  general-purpose model versus a future validated one.
- **GPS is captured once per session** (at scan start), not per-frame. If you need
  per-frame GPS (e.g. for long walks across a large farm), the browser can supply a
  GPS trail via `watchPosition()` — the one place this would plug in is flagged
  with a comment in `app/pipeline/orchestrator.py`.
- **No auth.** Anyone who can reach the server can upload scans. Fine for an MVP
  demo, not fine for anything beyond that.
- **Pipeline runs synchronously per detector, per frame** — fine for demo-scale
  scans (dozens of frames), but for longer scans you'd want to parallelize the
  Gemini calls (e.g. `asyncio.gather` across frames) before this goes to real users.

## How to add a new (validated) detector later

This is the part the whole architecture is built around, so it should be genuinely
easy:

1. Create a new class in `app/detectors/` that subclasses `Detector`
   (see `app/detectors/base.py`) and implements `run(frame) -> list[Detection]`.
2. Register the class in `DETECTOR_CLASSES` in `app/detectors/registry.py`.
3. Add a config entry in `DETECTOR_REGISTRY_CONFIG` in `app/config.py` — name,
   version, confidence threshold, any params your detector needs.

That's it. `app/pipeline/orchestrator.py` — the file that actually runs the
pipeline — never needs to change. It loops over whatever detectors are active in
config and persists whatever they return. You can also disable/re-enable
detectors, or run multiple versions side by side, purely through config.

Because raw evidence images and each detection's `raw_model_output` are retained
in the database and on disk, you can also **reprocess historical scans** against a
new detector once it exists, without re-visiting the farm.

## Deploying to Render

**1. Push to GitHub first** (Render deploys from a GitHub repo, not a zip upload):

```bash
cd farm-mvp
git init
git add .
git commit -m "Initial commit"
# create a new empty repo on github.com first, then:
git remote add origin https://github.com/<your-username>/<your-repo>.git
git branch -M main
git push -u origin main
```

`.gitignore` is already set up to exclude `venv/`, `.env`, the SQLite DB, and runtime evidence/upload files — none of that should ever be committed.

**2. On Render**: New → Blueprint → connect your GitHub repo. Render will read
`render.yaml` automatically and set up the service, including a **persistent
disk** mounted at `/var/data`.

This persistent disk matters more than it looks like it should: Render's
default filesystem is ephemeral and gets wiped on every redeploy or restart.
Without a persistent disk, every evidence image and the entire SQLite database
would vanish the next time you push a code change — which directly breaks the
"every observation must retain image evidence" requirement. `render.yaml`
already wires `DATA_DIR=/var/data` so the app writes there instead of the
ephemeral app folder.

**Note**: persistent disks require a paid Render plan (Starter or above) —
they are not available on the free tier. If you're testing on the free tier
first, everything will still *work*, you'll just lose evidence/DB data on
every redeploy until you attach a disk.

**3. Set your Gemini key**: in the Render dashboard, under your service →
Environment → add `GEMINI_API_KEY` with your real key. `render.yaml` deliberately
leaves this one out (`sync: false`) so it's never committed to the repo.

**4. Before going further than a demo**: `CORSMiddleware` in `app/main.py` is
currently set to `allow_origins=["*"]`, which is fine for local testing but
should be locked down to your actual deployed domain once this isn't just a
technical demo anymore.

## Project structure

```
app/
  main.py                    FastAPI app, mounts routes + static files
  config.py                  All settings + the detector registry config
  database.py                SQLAlchemy engine/session
  models.py                  ScanSession, Observation ORM models
  schemas.py                 API response schemas
  storage.py                 Evidence image saving
  detectors/
    base.py                  Detector interface (the contract)
    gemini_detector.py       Zero-shot Gemini implementation
    registry.py               Builds active detectors from config
  pipeline/
    frame_extraction.py      OpenCV frame sampling + blur filtering
    orchestrator.py          Wires extraction -> detectors -> storage -> DB
  routers/
    sessions.py               Upload / results / evidence-image endpoints
static/
  index.html                 Capture page (camera + GPS + upload)
  results.html                Results/report page (evidence grid)
scripts/
  test_upload.py              CLI test harness for local video files
evidence/                     Evidence images (created at runtime)
uploads/                      Raw uploaded videos (created at runtime)
```
