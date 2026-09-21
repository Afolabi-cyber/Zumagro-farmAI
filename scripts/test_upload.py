"""
Quick CLI test harness: upload a local video file to a running instance of
the API and poll until processing finishes, then print a summary.

Usage:
    python scripts/test_upload.py path/to/video.mp4 --farm-id ZUMAGRO-FARM-014 --lat 6.5244 --lon 3.3792

Make sure the server is running first: uvicorn app.main:app --reload
"""

import argparse
import time
import sys
import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video_path", help="Path to a test video file (mp4/mov/webm)")
    parser.add_argument("--farm-id", required=True)
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    print(f"Uploading {args.video_path} for farm {args.farm_id}...")
    with open(args.video_path, "rb") as f:
        files = {"video": (args.video_path, f, "video/mp4")}
        data = {"farm_id": args.farm_id}
        if args.lat is not None:
            data["lat"] = args.lat
        if args.lon is not None:
            data["lon"] = args.lon
        resp = requests.post(f"{args.api_base}/sessions/upload", data=data, files=files)

    if resp.status_code != 200:
        print("Upload failed:", resp.status_code, resp.text)
        sys.exit(1)

    session = resp.json()
    session_id = session["session_id"]
    print(f"Session created: {session_id}")
    print("Processing...")

    while True:
        r = requests.get(f"{args.api_base}/sessions/{session_id}")
        r.raise_for_status()
        detail = r.json()
        status = detail["status"]
        if status in ("completed", "failed"):
            break
        print(f"  status={status} ... waiting")
        time.sleep(3)

    print()
    print("=" * 50)
    print(f"Status: {detail['status']}")
    print(f"Frames extracted: {detail['frames_extracted']}, usable after filtering: {detail['frames_used']}")
    if detail.get("error_message"):
        print(f"Error: {detail['error_message']}")
    print(f"Observation counts: {detail['observation_counts']}")
    print(f"Total observations: {len(detail['observations'])}")
    print("=" * 50)
    print(f"\nView the full report at: {args.api_base}/app/results.html?session_id={session_id}")


if __name__ == "__main__":
    main()
