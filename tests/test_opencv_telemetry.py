"""Unit and integration tests for the OpenCV Agentic Vision Engine (Sprint 2)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from prometheus.analysis.analyzer import GeminiAnalyzer
from prometheus.analysis.opencv_telemetry import analyze_image_cv, analyze_video_cv
from prometheus.analysis.orb_ai import OrbAIService


def test_dark_low_contrast_image_triggers_clahe_agentic_action(tmp_path: Path):
    # Create a low-luminance, low-contrast 128x128 BGR image with a faint grid pattern
    img = np.full((128, 128, 3), 24, dtype=np.uint8)
    cv2.rectangle(img, (20, 20), (60, 60), (38, 30, 28), thickness=2)
    cv2.line(img, (10, 40), (118, 40), (42, 35, 30), thickness=2)

    img_path = tmp_path / "dark_scene.png"
    cv2.imwrite(str(img_path), img)
    out_dir = tmp_path / "run_out"

    telemetry = analyze_image_cv(img_path, output_dir=out_dir)
    payload = telemetry.to_dict()

    assert payload["opencv_version"] == cv2.__version__
    assert payload["compute_arch"] in {"x86_64", "ARM64", "CPU"}
    assert isinstance(payload["compute_badge"], str) and len(payload["compute_badge"]) > 0
    assert "simd_flags" in payload["compute_runtime"]
    assert payload["media_kind"] == "image"
    assert payload["processing_ms"] > 0.0
    assert payload["effective_fps"] > 0.0
    assert payload["clahe_triggered"] is True
    assert payload["clahe_applied"] is True
    assert telemetry.clahe_enhanced_path is not None
    assert telemetry.clahe_enhanced_path.name == "opencv_clahe_enhanced.jpg"
    assert telemetry.clahe_enhanced_path.is_file()

    # Check color & lighting telemetry
    cl = payload["color_and_lighting"]
    assert cl["mean_luminance"] < 60.0
    assert cl["lighting_key"] in {"low-key", "low-contrast"}
    assert len(cl["dominant_colors"]) >= 1
    for color in cl["dominant_colors"]:
        assert re.match(r"^#[0-9a-f]{6}$", color["hex"])
        assert 0.0 < color["weight_pct"] <= 100.0

    # Check sharpness & geometry telemetry (including Sprint 3 UI convenience keys)
    sg = payload["sharpness_and_geometry"]
    assert sg["laplacian_sharpness"] >= 0.0
    assert sg["sharpness_score"] == sg["laplacian_sharpness"]
    assert sg["sharpness_label"] == sg["sharpness_tier"]
    assert "composition_zone" in sg["saliency_center"]
    assert sg["saliency_region"] == sg["saliency_center"]["composition_zone"]
    assert "dominant_orientation" in sg["structural_lines"]
    assert sg["dominant_lines"] == sg["structural_lines"]["dominant_orientation"]

    # Check agentic decision & action loop
    actions = payload["agentic_actions"]
    assert any(a["type"] == "clahe_shadow_contrast_recovery" for a in actions)
    assert "Autonomous CLAHE" in payload["cv_grounding_brief"]


def test_video_optical_flow_detects_horizontal_pan_and_ranks_keyframes(tmp_path: Path):
    frame_paths: list[Path] = []
    # Generate 8 synthetic frames where a textured vertical bar shifts right (+6px per frame)
    for idx in range(8):
        canvas = np.full((120, 200, 3), 30, dtype=np.uint8)
        x_start = 20 + idx * 8
        cv2.rectangle(canvas, (x_start, 20), (x_start + 36, 100), (220, 180, 90), thickness=-1)
        cv2.rectangle(canvas, (x_start + 6, 30), (x_start + 30, 90), (40, 60, 210), thickness=2)
        # Make one frame intentionally blurry to verify sharpness-gated keyframe ranking
        if idx == 3:
            canvas = cv2.GaussianBlur(canvas, (21, 21), 8.0)
        fpath = tmp_path / f"frame_{idx:03d}.png"
        cv2.imwrite(str(fpath), canvas)
        frame_paths.append(fpath)

    telemetry = analyze_video_cv(None, frame_paths, output_dir=tmp_path)
    payload = telemetry.to_dict()

    assert payload["media_kind"] == "video"
    assert payload["processing_ms"] > 0.0
    motion = payload["motion_and_continuity"]
    assert motion["frames_processed"] == 8
    assert motion["effective_fps"] > 0.0
    assert motion["mean_dx"] > 0.35
    assert motion["dominant_motion"] == "pan-right"
    assert -1.0 <= motion["mean_hist_correlation"] <= 1.0

    # Verify sharpness-gated keyframe ranking flagged the blurred frame last
    ranking = motion["keyframe_ranking"]
    assert len(ranking) == 8
    assert ranking[-1]["file"] == "frame_003.png"
    assert ranking[0]["sharpness"] > ranking[-1]["sharpness"]
    assert any(a["type"] == "sharpness_gated_keyframe_ranking" for a in payload["agentic_actions"])


def test_orb_ai_service_attaches_opencv_telemetry_and_clahe_frame(tmp_path: Path):
    img = np.full((64, 64, 3), 20, dtype=np.uint8)
    cv2.circle(img, (32, 32), 16, (35, 35, 40), thickness=-1)
    img_path = tmp_path / "dark_input.png"
    cv2.imwrite(str(img_path), img)

    calls = []

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text=json.dumps({
                "prompt": "A moody low-key circular form in shadow",
                "visual_analysis": {
                    "subject_and_scene": "Circular silhouette in dark space",
                    "composition": "Center-weighted framing",
                    "lighting": "Low-key shadow lighting",
                    "color_palette": "Deep charcoal and slate tones",
                },
                "refinements": ["Add rim lighting"],
            }))

    service = OrbAIService.__new__(OrbAIService)
    service.analyzer = GeminiAnalyzer(model="test-model", client=SimpleNamespace(models=FakeModels()))
    service.provider = "gemini"
    service.model = "test-model"

    run_dir = tmp_path / "job_run"
    result = service.image("decode", img_path, run_dir=run_dir)

    assert "opencv_telemetry" in result
    assert result["opencv_telemetry"]["clahe_triggered"] is True
    assert (run_dir / "opencv_clahe_enhanced.jpg").is_file()

    # Verify Gemini received: [0] text with OpenCV grounding brief, [1] original image, [2] CLAHE image
    contents = calls[0]["contents"]
    assert len(contents) == 3
    assert "[OpenCV Deterministic Telemetry" in contents[0].text
    assert contents[1].inline_data.data == img_path.read_bytes()
    assert contents[2].inline_data.mime_type == "image/jpeg"


def test_opencv_native_video_fallbacks_when_ffmpeg_missing(tmp_path: Path, monkeypatch):
    from prometheus.config import SamplingConfig
    from prometheus.video.probe import probe_video
    from prometheus.video.sampler import FrameSampler
    from prometheus.video.scene_detection import detect_scene_cuts
    from prometheus.video.tools import VideoToolError

    video_path = tmp_path / "synthetic.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, 12.0, (160, 120))
    for idx in range(24):
        frame = np.full((120, 160, 3), 25 if idx < 12 else 220, dtype=np.uint8)
        cv2.circle(frame, (30 + idx * 3, 60), 16, (0, 180, 255), -1)
        writer.write(frame)
    writer.release()

    def _missing_tool(name: str) -> str:
        raise VideoToolError(f"Required external tool '{name}' is unavailable.")

    monkeypatch.setattr("prometheus.video.probe.resolve_tool", _missing_tool)
    monkeypatch.setattr("prometheus.video.segmenter.resolve_tool", _missing_tool)
    monkeypatch.setattr("prometheus.video.sampler.resolve_tool", _missing_tool)

    metadata = probe_video(video_path)
    assert metadata.width == 160
    assert metadata.height == 120
    assert metadata.duration >= 1.5

    cuts = detect_scene_cuts("__missing_ffmpeg_binary__", str(video_path), metadata.duration, 0.25)
    assert isinstance(cuts, list)
    assert len(cuts) >= 1

    sampler = FrameSampler(SamplingConfig(strategy="uniform", frame_count=3))
    sampled = sampler.sample(metadata, tmp_path / "frames")
    assert len(sampled) == 3
    assert all(f.path.is_file() for f in sampled)


