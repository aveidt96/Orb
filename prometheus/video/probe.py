from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from prometheus.errors import PrometheusError
from prometheus.video.tools import VideoToolError, resolve_tool
from prometheus.performance import metric, process_run, timed


@dataclass
class VideoMetadata:
    path: str
    container: str
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    pixel_format: str
    bitrate: int
    frame_count: int | None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def aspect_ratio(self) -> str:
        if self.width <= 0 or self.height <= 0:
            return "unknown"
        a, b = self.width, self.height
        while b:
            a, b = b, a % b
        return f"{self.width // a}:{self.height // a}"


def video_identity(path: Path | str) -> tuple:
    """Internal identity guard for reusing a probe of an unchanged upload."""
    resolved = Path(path).resolve()
    stat = resolved.stat()
    return (str(resolved), stat.st_dev, stat.st_ino, stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns)


@dataclass(frozen=True)
class ValidatedVideo:
    metadata: VideoMetadata
    identity: tuple

    def matches(self, path: Path | str) -> bool:
        try:
            return self.identity == video_identity(path) and self.metadata.path == str(Path(path).resolve())
        except OSError:
            return False


def _probe_video_opencv(path: Path, fallback_error: Exception) -> VideoMetadata:
    try:
        import cv2
    except ImportError:
        raise fallback_error

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise fallback_error
        ok, first_frame = cap.read()
        if not ok or first_frame is None:
            raise fallback_error
        height, width = first_frame.shape[:2]
        w_prop = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or width)
        h_prop = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or height)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0.0 or fps > 240.0:
            fps = 24.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count <= 0:
            count = 1
            while True:
                ok_next, _ = cap.read()
                if not ok_next:
                    break
                count += 1
            frame_count = count
        duration = max(0.04, float(frame_count) / fps)
        size_bytes = path.stat().st_size
        bitrate = int((size_bytes * 8) / max(0.1, duration))
        metric("video_duration_s", duration)
        metric("width", w_prop)
        metric("height", h_prop)
        return VideoMetadata(
            path=str(path),
            container=path.suffix.lstrip(".").lower() or "mp4",
            duration=round(duration, 3),
            width=w_prop,
            height=h_prop,
            fps=round(fps, 3),
            codec="h264",
            pixel_format="yuv420p",
            bitrate=bitrate,
            frame_count=frame_count,
        )
    finally:
        cap.release()


@timed("ffprobe")
def probe_video(video_path: Path | str) -> VideoMetadata:
    path = Path(video_path).resolve()
    if not path.is_file():
        raise PrometheusError(f"Video file not found: {path}")
    try:
        ffprobe_bin = resolve_tool("ffprobe")
        cmd = [
            ffprobe_bin,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        try:
            result = process_run(subprocess.run, "ffprobe", cmd, capture_output=True, text=True, timeout=30)
        except FileNotFoundError as exc:
            raise VideoToolError(f"ffprobe executable not found: {cmd[0]}") from exc
        except OSError as exc:
            raise VideoToolError(f"Could not start ffprobe executable {cmd[0]}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise PrometheusError(f"ffprobe timed out for {path}") from exc
        if result.returncode != 0:
            raise PrometheusError(f"ffprobe failed for {path}: {result.stderr.strip()}")
        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise PrometheusError(f"Could not parse ffprobe output for {path}: {exc}") from exc

        streams = data.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if video_stream is None:
            raise PrometheusError(f"No video stream found in {path}")

        fmt = data.get("format", {})
        duration = float(fmt.get("duration") or video_stream.get("duration") or 0.0)
        if duration <= 0:
            raise PrometheusError(f"Could not determine duration for {path}")

        fps = _parse_frame_rate(video_stream.get("r_frame_rate") or video_stream.get("avg_frame_rate") or "0/1")
        if fps <= 0:
            fps = 25.0

        nb_frames = video_stream.get("nb_frames")
        metric("video_duration_s", duration)
        metric("width", int(video_stream.get("width") or 0))
        metric("height", int(video_stream.get("height") or 0))
        return VideoMetadata(
            path=str(path),
            container=fmt.get("format_name", "unknown"),
            duration=duration,
            width=int(video_stream.get("width") or 0),
            height=int(video_stream.get("height") or 0),
            fps=round(fps, 3),
            codec=video_stream.get("codec_name", "unknown"),
            pixel_format=video_stream.get("pix_fmt", "unknown"),
            bitrate=int(fmt.get("bit_rate") or 0),
            frame_count=int(nb_frames) if nb_frames and nb_frames.isdigit() else None,
        )
    except (VideoToolError, PrometheusError) as exc:
        return _probe_video_opencv(path, exc)


def _parse_frame_rate(rate: str) -> float:
    try:
        num, _, den = rate.partition("/")
        numerator = float(num)
        denominator = float(den) if den else 1.0
        if denominator == 0:
            return 0.0
        return numerator / denominator
    except ValueError:
        return 0.0

