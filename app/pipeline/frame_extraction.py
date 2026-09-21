"""
Extracts a small, quality-filtered set of frames spread evenly across the
whole scan, each tagged with its offset (seconds from scan start).

MAX_FRAMES_PER_SESSION (default 5) is the single knob that controls both
how many Gemini calls a scan costs and how the scan is sampled: the
extractor picks that many timestamps evenly spaced from the start to the
end of the video (e.g. for 5: ~0%, 25%, 50%, 75%, 100%), so a two-minute
walk through a field is actually represented start to finish rather than
only its first few seconds.

This deliberately does NOT just read sequentially from frame 0 and stop
once it hits the cap - that was the earlier (buggy) approach and it meant
a low cap only ever looked at the very start of a scan. Each target point
also gets a small local search window (+/- ~0.5s) for the sharpest nearby
frame, so a single blurry moment doesn't cost that entire segment of the
scan; if nothing in the window clears BLUR_THRESHOLD, the sharpest one
found in the window is used anyway rather than dropping that point.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from app.config import BLUR_THRESHOLD, MAX_FRAMES_PER_SESSION


@dataclass
class ExtractedFrame:
    frame: np.ndarray  # BGR image
    offset_seconds: float  # time since video start
    sharpness: float


def _sharpness_score(frame: np.ndarray) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def _count_frames(video_path: str) -> int:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    count = 0
    while cap.grab():
        count += 1
    cap.release()
    return count


def extract_frames(video_path: str) -> tuple[list[ExtractedFrame], int]:
    total_frames = _count_frames(video_path)
    if total_frames <= 0:
        raise ValueError(f"Video appears to have no readable frames: {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    n = max(1, MAX_FRAMES_PER_SESSION)
    if n == 1 or total_frames == 1:
        target_indices = [total_frames // 2]
    else:
        target_indices = sorted(
            {round(i * (total_frames - 1) / (n - 1)) for i in range(n)}
        )

    radius = max(1, round(fps * 0.5))
    windows = {
        t: (max(0, t - radius), min(total_frames - 1, t + radius)) for t in target_indices
    }
    candidates: dict[int, tuple[np.ndarray, float, int] | None] = {t: None for t in target_indices}

    idx = 0
    ret, frame = cap.read()
    while ret:
        for t, (lo, hi) in windows.items():
            if lo <= idx <= hi:
                sharpness = _sharpness_score(frame)
                current = candidates[t]
                if current is None:
                    candidates[t] = (frame.copy(), sharpness, idx)
                else:
                    _, cur_sharp, cur_idx = current
                    cur_ok = cur_sharp >= BLUR_THRESHOLD
                    new_ok = sharpness >= BLUR_THRESHOLD
                    if new_ok and not cur_ok:
                        candidates[t] = (frame.copy(), sharpness, idx)
                    elif new_ok == cur_ok and abs(idx - t) < abs(cur_idx - t):
                        candidates[t] = (frame.copy(), sharpness, idx)
        idx += 1
        ret, frame = cap.read()

    cap.release()

    usable: list[ExtractedFrame] = []
    for t in target_indices:
        cand = candidates[t]
        if cand is not None:
            f, sharp, found_idx = cand
            usable.append(ExtractedFrame(frame=f, offset_seconds=found_idx / fps, sharpness=sharp))

    return usable, len(target_indices)