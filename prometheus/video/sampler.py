from __future__ import annotations

import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path

from prometheus.config import SamplingConfig
from prometheus.errors import PrometheusError
from prometheus.video.probe import VideoMetadata
from prometheus.video.tools import VideoToolError, resolve_tool
from prometheus.performance import metric, process_run, timed


@dataclass
class SampledFrame:
    index: int
    timestamp: float
    path: Path

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp": round(self.timestamp, 3),
            "file": self.path.name,
        }


def uniform_timestamps(start: float, end: float, count: int) -> list[float]:
    count = max(1, count)
    return [start + (end - start) * (i + 0.5) / count for i in range(count)]


def frame_name(index: int, timestamp: float, image_format: str) -> str:
    return f"frame_{index:03d}_t{timestamp:08.3f}s.{image_format}"


def canonical_timestamp(timestamp: float) -> str:
    # Identical to the existing FFmpeg -ss argument, not a nearby-time heuristic.
    return f"{timestamp:.3f}"


def cap_evenly(items: list, limit: int) -> list:
    if len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def _extract_frame_opencv(
    video_path: str,
    timestamp: float,
    destination: Path,
    image_format: str,
    image_quality: int,
    fallback_error: Exception,
) -> None:
    try:
        import cv2
    except ImportError:
        raise fallback_error

    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise fallback_error
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(timestamp) * 1000.0))
        ok, frame = cap.read()
        if not ok or frame is None:
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total - 1))
                ok, frame = cap.read()
            if not ok or frame is None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = cap.read()
        if not ok or frame is None:
            raise fallback_error

        destination.parent.mkdir(parents=True, exist_ok=True)
        params: list[int] = []
        if image_format.lower() in {"jpg", "jpeg"}:
            jpg_q = max(60, min(95, 100 - int(image_quality) * 3))
            params = [int(cv2.IMWRITE_JPEG_QUALITY), jpg_q]
        if not cv2.imwrite(str(destination), frame, params) or not destination.is_file():
            raise fallback_error
    finally:
        cap.release()


@timed("frame_extraction")
def extract_frame(
    ffmpeg: str,
    video_path: str,
    timestamp: float,
    destination: Path,
    image_format: str,
    image_quality: int,
) -> None:
    cmd = [
        ffmpeg,
        "-nostdin", "-loglevel", "error", "-y",
        "-ss", canonical_timestamp(timestamp),
        "-i", video_path,
        "-frames:v", "1",
    ]
    if image_format == "jpg":
        cmd += ["-q:v", str(image_quality)]
    cmd.append(str(destination))
    try:
        try:
            result = process_run(subprocess.run, "ffmpeg", cmd, capture_output=True, text=True, timeout=30)
        except OSError as exc:
            raise VideoToolError(f"Could not start ffmpeg executable {ffmpeg}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise PrometheusError(f"Frame extraction timed out at t={timestamp:.3f}s") from exc
        if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
            detail = result.stderr.strip() or "no output frame produced"
            raise PrometheusError(f"Frame extraction failed at t={timestamp:.3f}s: {detail}")
    except (VideoToolError, PrometheusError) as exc:
        _extract_frame_opencv(video_path, timestamp, destination, image_format, image_quality, exc)


class FrameSampler:
    def __init__(self, config: SamplingConfig):
        self.config = config
        try:
            self._ffmpeg = resolve_tool("ffmpeg")
        except VideoToolError:
            self._ffmpeg = "ffmpeg"

    def sample(self, video: VideoMetadata, output_dir: Path, *, extraction_cache: dict | None = None) -> list[SampledFrame]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        return self._extract_all(video, self._plan(video), output_dir, extraction_cache)

    def sample_range(
        self,
        video: VideoMetadata,
        start: float,
        end: float,
        count: int,
        output_dir: Path,
        *, extraction_cache: dict | None = None,
    ) -> list[SampledFrame]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        return self._extract_all(video, uniform_timestamps(start, end, count), output_dir, extraction_cache)

    def _extract_all(
        self, video: VideoMetadata, timestamps: list[float], output_dir: Path,
        extraction_cache: dict | None = None,
    ) -> list[SampledFrame]:
        frames: list[SampledFrame] = []
        for index, timestamp in enumerate(timestamps):
            path = output_dir / frame_name(index, timestamp, self.config.image_format)
            key = (video.path, canonical_timestamp(timestamp), self.config.image_format, self.config.image_quality)
            cached = extraction_cache.get(key) if extraction_cache is not None else None
            if cached is not None:
                if cached != path:
                    shutil.copyfile(cached, path)
                metric("frame_cache_hits")
            else:
                extract_frame(
                    self._ffmpeg, video.path, timestamp, path,
                    self.config.image_format, self.config.image_quality,
                )
                metric("unique_extracted_frames")
                if extraction_cache is not None:
                    extraction_cache[key] = path
            frames.append(SampledFrame(index=index, timestamp=timestamp, path=path))
            metric("frames")
        return frames

    def _plan(self, video: VideoMetadata) -> list[float]:
        if self.config.strategy == "uniform":
            timestamps = uniform_timestamps(0.0, video.duration, self.config.frame_count)
            return cap_evenly(timestamps, self.config.max_frames)
        if self.config.strategy == "interval":
            return self._interval_timestamps(video.duration, self.config.interval_seconds)
        raise PrometheusError(f"Unknown sampling strategy: {self.config.strategy}")

    def _interval_timestamps(self, duration: float, interval: float) -> list[float]:
        step_count = int(duration / interval) + (1 if duration % interval else 0)
        timestamps = [(i + 0.5) * interval for i in range(max(1, step_count))]
        timestamps = [t for t in timestamps if t < duration]
        if not timestamps:
            timestamps = [duration / 2]
        return cap_evenly(timestamps, self.config.max_frames)
