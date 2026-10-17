from __future__ import annotations

from dataclasses import dataclass

from prometheus.config import SegmentationConfig
from prometheus.video.probe import VideoMetadata
from prometheus.video.scene_detection import detect_scene_cuts
from prometheus.video.tools import VideoToolError, resolve_tool


@dataclass
class Scene:
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
        }


class SceneSegmenter:
    def __init__(self, config: SegmentationConfig):
        self.config = config
        try:
            self._ffmpeg = resolve_tool("ffmpeg")
        except VideoToolError:
            self._ffmpeg = "ffmpeg"

    def segment(self, video: VideoMetadata) -> list[Scene]:
        cuts = detect_scene_cuts(
            self._ffmpeg, video.path, video.duration, self.config.scene_threshold
        )
        boundaries = [0.0] + cuts + [video.duration]
        spans = build_scene_spans(
            boundaries, self.config.min_scene_duration, self.config.max_scenes
        )
        return [
            Scene(index=index, start=start, end=end)
            for index, (start, end) in enumerate(spans)
        ]


def build_scene_spans(
    boundaries: list[float],
    min_scene_duration: float,
    max_scenes: int,
) -> list[tuple[float, float]]:
    spans = [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]
    spans = _merge_short_spans(spans, min_scene_duration)
    spans = _cap_scene_count(spans, max_scenes)
    return spans


def _merge_short_spans(
    spans: list[tuple[float, float]], min_duration: float
) -> list[tuple[float, float]]:
    result = [[start, end] for start, end in spans]
    i = 0
    while i < len(result):
        start, end = result[i]
        if end - start < min_duration and len(result) > 1:
            if i > 0:
                result[i - 1][1] = end
                result.pop(i)
            else:
                result[1][0] = start
                result.pop(0)
        else:
            i += 1
    return [(start, end) for start, end in result]


def _cap_scene_count(
    spans: list[tuple[float, float]], max_scenes: int
) -> list[tuple[float, float]]:
    result = [[start, end] for start, end in spans]
    while len(result) > max_scenes:
        shortest = min(range(len(result)), key=lambda i: result[i][1] - result[i][0])
        if shortest == 0:
            neighbor = 1
        elif shortest == len(result) - 1:
            neighbor = len(result) - 2
        else:
            left_len = result[shortest - 1][1] - result[shortest - 1][0]
            right_len = result[shortest + 1][1] - result[shortest + 1][0]
            neighbor = shortest - 1 if left_len <= right_len else shortest + 1
        if neighbor < shortest:
            result[neighbor][1] = result[shortest][1]
        else:
            result[neighbor][0] = result[shortest][0]
        result.pop(shortest)
    return [(start, end) for start, end in result]
