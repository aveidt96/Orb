from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from pathlib import Path
from typing import Callable

from prometheus.analysis.analyzer import MultimodalAnalyzer, create_analyzer
from prometheus.analysis.prompt_builder import (
    build_reconstructed_prompt,
    build_scene_reconstruction_prompt,
)
from prometheus.analysis.schema import AnalysisReport
from prometheus.config import PrometheusConfig
from prometheus.errors import PrometheusError
from prometheus.storage import (
    RunOutput,
    prepare_run_directory,
    prepare_scene_directory,
    save_analysis,
    save_manifest,
    save_prompt,
    save_scene_analysis,
    save_scene_prompt,
)
from prometheus.video.probe import ValidatedVideo, VideoMetadata, probe_video
from prometheus.video.sampler import FrameSampler, SampledFrame
from prometheus.video.segmenter import Scene, SceneSegmenter
from prometheus.analysis.opencv_telemetry import analyze_video_cv
from prometheus.performance import metric, stage


@dataclass
class PipelineResult:
    metadata: VideoMetadata
    frames: list[SampledFrame]
    scenes: list[Scene]
    report: AnalysisReport
    prompt: str
    output: RunOutput
    opencv_telemetry: dict | None = None


class PrometheusPipeline:
    def __init__(
        self,
        config: PrometheusConfig | None = None,
        analyzer: MultimodalAnalyzer | None = None,
    ):
        self.config = config or PrometheusConfig()
        self.analyzer = analyzer or create_analyzer(self.config.analyzer)
        self.sampler = FrameSampler(self.config.sampling)
        self.segmenter = SceneSegmenter(self.config.segmentation)

    def run(
        self,
        video_path: Path | str,
        progress: Callable[[str], None] | None = None,
        *, validated_video: ValidatedVideo | None = None,
    ) -> PipelineResult:
        notify = progress or (lambda message: None)
        config = self.config
        config.validate()
        notify("Inspecting video")
        metadata = (validated_video.metadata if validated_video is not None and validated_video.matches(video_path)
                    else probe_video(video_path))
        # Scoped to this immutable source and this run; never reused across jobs.
        extraction_cache: dict = {}
        run_dir, frames_dir = prepare_run_directory(video_path, config.output.directory)
        notify("Detecting scene cuts")
        scenes = self.segmenter.segment(metadata)
        metric("scene_count", len(scenes))
        scene_summaries = self._analyze_scenes(metadata, scenes, run_dir, notify, extraction_cache)
        notify("Sampling representative frames")
        frames = self.sampler.sample(metadata, frames_dir, extraction_cache=extraction_cache)
        metric("global_frames", len(frames))
        if not frames:
            raise PrometheusError(f"No frames could be extracted from {metadata.path}")
        cv_telemetry_dict: dict | None = None
        try:
            with stage("opencv_perception"):
                cv_telemetry = analyze_video_cv(
                    Path(metadata.path),
                    [frame.path for frame in frames],
                    output_dir=run_dir,
                )
                cv_telemetry_dict = cv_telemetry.to_dict()
                setattr(metadata, "_cv_grounding_brief", cv_telemetry.cv_grounding_brief)
        except Exception:
            cv_telemetry_dict = None
        notify("Analyzing shared characteristics")
        report = self.analyzer.analyze(metadata, frames, scene_context=scene_summaries)
        report.scenes = scene_summaries
        notify("Saving results")
        prompt = build_reconstructed_prompt(report)

        manifest_path = save_manifest(run_dir, metadata, frames, config.sampling, scenes=scene_summaries)
        analysis_path = save_analysis(run_dir, report)
        prompt_md_path, prompt_txt_path = save_prompt(run_dir, prompt)
        output = RunOutput(
            run_dir=run_dir,
            frames_dir=frames_dir,
            scenes_dir=run_dir / "scenes",
            manifest_path=manifest_path,
            analysis_path=analysis_path,
            prompt_md_path=prompt_md_path,
            prompt_txt_path=prompt_txt_path,
        )
        return PipelineResult(
            metadata=metadata,
            frames=frames,
            scenes=scenes,
            report=report,
            prompt=prompt,
            output=output,
            opencv_telemetry=cv_telemetry_dict,
        )

    def _analyze_scenes(
        self,
        metadata: VideoMetadata,
        scenes: list[Scene],
        run_dir: Path,
        notify: Callable[[str], None],
        extraction_cache: dict | None = None,
    ) -> list[dict]:
        summaries: list[dict] = []
        total = len(scenes)
        prepared = []
        # FFmpeg remains sequential. Only independent provider operations overlap.
        for scene in scenes:
            scene_dir = prepare_scene_directory(run_dir, scene)
            frames = self.sampler.sample_range(
                metadata,
                scene.start,
                scene.end,
                self.config.segmentation.frames_per_scene,
                scene_dir / "frames",
                extraction_cache=extraction_cache,
            )
            metric("scene_frames", len(frames))
            prepared.append((scene, scene_dir, frames))

        def save_scene(item, analysis):
            scene, scene_dir, frames = item
            prompt = build_scene_reconstruction_prompt(analysis)
            analysis_path = save_scene_analysis(scene_dir, analysis)
            prompt_md_path, _ = save_scene_prompt(scene_dir, prompt)
            scene_info = scene.to_dict()
            scene_info["description"] = analysis.description
            scene_info["frames"] = [frame.to_dict() for frame in frames]
            scene_info["analysis_file"] = str(analysis_path.relative_to(run_dir))
            scene_info["prompt_file"] = str(prompt_md_path.relative_to(run_dir))
            summaries.append(scene_info)

        # At most two outstanding scene calls, including their existing retries.
        # Refill on completion, but assemble in original order. On failure, stop
        # scheduling and join already-running calls before source cleanup/settlement.
        with stage("scene_ai_wall"):
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="orb-scene") as executor:
                pending = {}
                items = iter(enumerate(prepared))
                analyses = [None] * total
                completed = 0

                def submit_next():
                    item = next(items, None)
                    if item is not None:
                        position, (scene, _, frames) = item
                        future = executor.submit(copy_context().run, self.analyzer.analyze_scene, metadata, scene, frames)
                        pending[future] = position

                try:
                    submit_next()
                    submit_next()
                    if total:
                        notify(f"Analyzing scene 1 of {total}")
                    while pending:
                        done, _ = wait(pending, return_when=FIRST_COMPLETED)
                        # Observe all completed failures before dispatching more.
                        for future in sorted(done, key=pending.get):
                            analyses[pending.pop(future)] = future.result()
                            completed += 1
                        notify(f"Analyzing scene {min(completed + 1, total)} of {total}")
                        for _ in done:
                            submit_next()
                finally:
                    for future in pending:
                        future.cancel()
        for item, analysis in zip(prepared, analyses):
            save_scene(item, analysis)
        return summaries
