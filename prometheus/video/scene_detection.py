from __future__ import annotations

import re
import subprocess

from prometheus.errors import PrometheusError
from prometheus.video.tools import VideoToolError
from prometheus.performance import process_run, timed

_CUT_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")
_DEDUP_WINDOW = 0.2


def _detect_scene_cuts_opencv(
    video_path: str, duration: float, threshold: float, fallback_error: Exception
) -> list[float]:
    try:
        import cv2
    except ImportError:
        raise fallback_error

    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise fallback_error
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
        if fps <= 0.0 or fps > 240.0:
            fps = 24.0
        step = max(1, int(round(fps / 6.0)))
        prev_hist = None
        frame_idx = 0
        cuts: list[float] = []
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if frame_idx % step == 0:
                small = cv2.resize(frame, (128, 72), interpolation=cv2.INTER_AREA)
                hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [24, 24], [0, 180, 0, 256])
                cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
                if prev_hist is not None:
                    corr = float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL))
                    diff = max(0.0, 1.0 - corr)
                    t = frame_idx / fps
                    if diff > threshold and 0.0 < t < duration:
                        if not cuts or t - cuts[-1] > _DEDUP_WINDOW:
                            cuts.append(round(t, 3))
                prev_hist = hist
            frame_idx += 1
        return cuts
    finally:
        cap.release()


@timed("scene_detection")
def detect_scene_cuts(ffmpeg: str, video_path: str, duration: float, threshold: float) -> list[float]:
    cmd = [
        ffmpeg,
        "-nostdin",
        "-i", video_path,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    try:
        try:
            result = process_run(subprocess.run, "ffmpeg", cmd, capture_output=True, text=True, timeout=60)
        except OSError as exc:
            raise VideoToolError(f"Could not start ffmpeg executable {ffmpeg}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise PrometheusError(f"Scene detection timed out for {video_path}") from exc
        if result.returncode != 0:
            raise PrometheusError(f"Scene detection failed for {video_path}: {result.stderr.strip()}")
        timestamps = sorted({float(m) for m in _CUT_RE.findall(result.stderr) if 0 <= float(m) < duration})
        deduped: list[float] = []
        for t in timestamps:
            if not deduped or t - deduped[-1] > _DEDUP_WINDOW:
                deduped.append(t)
        return deduped
    except (VideoToolError, PrometheusError) as exc:
        return _detect_scene_cuts_opencv(video_path, duration, threshold, exc)

