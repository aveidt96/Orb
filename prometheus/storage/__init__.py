from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prometheus.analysis.scene_schema import SceneAnalysis
from prometheus.analysis.schema import AnalysisReport
from prometheus.config import SamplingConfig
from prometheus.performance import timed
from prometheus.storage.aws_s3 import (
    build_aws_integration_metadata,
    get_aws_s3_config,
    load_serverless_frame_from_s3,
    load_serverless_job_state_from_s3,
    save_serverless_job_state_to_s3,
    sync_job_artifacts_to_s3,
    sync_opencv_artifacts_to_s3,
)
from prometheus.video.probe import VideoMetadata
from prometheus.video.sampler import SampledFrame
from prometheus.video.segmenter import Scene


@dataclass
class RunOutput:
    run_dir: Path
    frames_dir: Path
    scenes_dir: Path
    manifest_path: Path
    analysis_path: Path
    prompt_md_path: Path
    prompt_txt_path: Path


def prepare_run_directory(video_path: Path | str, base_dir: Path | str) -> tuple[Path, Path]:
    stem = re.sub(r"[^\w\-]+", "_", Path(video_path).stem) or "video"
    run_dir = Path(base_dir) / stem
    frames_dir = run_dir / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    scenes_dir = run_dir / "scenes"
    if scenes_dir.exists():
        shutil.rmtree(scenes_dir)
    scenes_dir.mkdir(parents=True, exist_ok=True)
    return run_dir, frames_dir


def prepare_scene_directory(run_dir: Path, scene: Scene) -> Path:
    scene_dir = Path(run_dir) / "scenes" / f"scene_{scene.index:03d}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    return scene_dir


@timed("artifact_persistence")
def save_manifest(
    run_dir: Path,
    metadata: VideoMetadata,
    frames: list[SampledFrame],
    sampling: SamplingConfig,
    scenes: list[dict[str, Any]] | None = None,
) -> Path:
    manifest = {
        "video": metadata.to_dict(),
        "sampling": {
            "strategy": sampling.strategy,
            "frame_count": sampling.frame_count,
            "interval_seconds": sampling.interval_seconds,
            "max_frames": sampling.max_frames,
            "image_format": sampling.image_format,
        },
        "frames": [frame.to_dict() for frame in frames],
        "scenes": scenes or [],
    }
    path = Path(run_dir) / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


@timed("artifact_persistence")
def save_analysis(run_dir: Path, report: AnalysisReport) -> Path:
    path = Path(run_dir) / "analysis.json"
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path


@timed("artifact_persistence")
def save_prompt(run_dir: Path, prompt: str) -> tuple[Path, Path]:
    md_path = Path(run_dir) / "reconstructed_prompt.md"
    txt_path = Path(run_dir) / "reconstructed_prompt.txt"
    md_path.write_text(prompt, encoding="utf-8")
    txt_path.write_text(_plain_text(prompt), encoding="utf-8")
    return md_path, txt_path


@timed("artifact_persistence")
def save_scene_analysis(scene_dir: Path, analysis: SceneAnalysis) -> Path:
    path = Path(scene_dir) / "scene.json"
    path.write_text(json.dumps(analysis.to_dict(), indent=2), encoding="utf-8")
    return path


@timed("artifact_persistence")
def save_scene_prompt(scene_dir: Path, prompt: str) -> tuple[Path, Path]:
    md_path = Path(scene_dir) / "reconstruction_prompt.md"
    txt_path = Path(scene_dir) / "reconstruction_prompt.txt"
    md_path.write_text(prompt, encoding="utf-8")
    txt_path.write_text(_plain_text(prompt), encoding="utf-8")
    return md_path, txt_path


def _plain_text(markdown: str) -> str:
    text = re.sub(r"^#{1,6}\s*", "", markdown, flags=re.MULTILINE)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    return text


__all__ = [
    "RunOutput",
    "build_aws_integration_metadata",
    "get_aws_s3_config",
    "load_serverless_frame_from_s3",
    "load_serverless_job_state_from_s3",
    "prepare_run_directory",
    "prepare_scene_directory",
    "save_analysis",
    "save_manifest",
    "save_prompt",
    "save_scene_analysis",
    "save_scene_prompt",
    "save_serverless_job_state_to_s3",
    "sync_job_artifacts_to_s3",
    "sync_opencv_artifacts_to_s3",
]
