from __future__ import annotations

import base64
import json
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

from prometheus.analysis.scene_schema import (
    SCENE_CATEGORIES,
    SCENE_CATEGORY_KEYS,
    SceneAnalysis,
)
from prometheus.analysis.schema import CATEGORIES, AnalysisReport, CategoryFinding
from prometheus.config import AnalyzerConfig
from prometheus.errors import PrometheusError
from prometheus.video.probe import VideoMetadata
from prometheus.video.sampler import SampledFrame
from prometheus.video.segmenter import Scene
from prometheus.performance import ai_call, attempt as perf_attempt, categorized, retry_wait, stage, timed

RETRYABLE_STATUS_CODES = (429, 500, 503)
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0

SceneContext = list[dict[str, Any]]


class ModelOutputError(PrometheusError):
    """A model response was received but cannot be used as an analysis."""


class MultimodalAnalyzer(ABC):
    @abstractmethod
    def analyze(
        self,
        metadata: VideoMetadata,
        frames: list[SampledFrame],
        scene_context: SceneContext | None = None,
    ) -> AnalysisReport:
        raise NotImplementedError

    @abstractmethod
    def analyze_scene(
        self, metadata: VideoMetadata, scene: Scene, frames: list[SampledFrame]
    ) -> SceneAnalysis:
        raise NotImplementedError

    @property
    @abstractmethod
    def provenance(self) -> dict[str, str]:
        raise NotImplementedError


class MockAnalyzer(MultimodalAnalyzer):
    @property
    def provenance(self) -> dict[str, str]:
        return {"provider": "mock", "model": "mock", "mode": "mock"}

    def analyze(
        self,
        metadata: VideoMetadata,
        frames: list[SampledFrame],
        scene_context: SceneContext | None = None,
    ) -> AnalysisReport:
        timestamps = ", ".join(f"{f.timestamp:.2f}s" for f in frames)
        report = AnalysisReport(
            video_metadata=metadata.to_dict(),
            frames=[f.to_dict() for f in frames],
            summary="Mock analysis: no vision model was connected, so findings are placeholders.",
            analyzer=self.provenance,
        )
        for spec in CATEGORIES:
            report.categories[spec.key] = CategoryFinding(
                observations=[
                    f"Source video: {metadata.width}x{metadata.height} at {metadata.fps} fps, {metadata.duration:.2f}s.",
                    f"{len(frames)} frames were sampled at t=[{timestamps}].",
                ],
                inferences=[
                    f"Placeholder inference for {spec.label}; connect a multimodal provider to populate real findings."
                ],
                confidence=0.1,
            )
        report.validate()
        return report

    def analyze_scene(
        self, metadata: VideoMetadata, scene: Scene, frames: list[SampledFrame]
    ) -> SceneAnalysis:
        timestamps = ", ".join(f"{f.timestamp:.2f}s" for f in frames)
        analysis = SceneAnalysis(
            scene=scene,
            description="Mock scene analysis: no vision model was connected.",
            analyzer=self.provenance,
        )
        for spec in SCENE_CATEGORIES:
            analysis.categories[spec.key] = CategoryFinding(
                observations=[
                    f"Scene spans t={scene.start:.2f}s to t={scene.end:.2f}s.",
                    f"{len(frames)} frames were sampled at t=[{timestamps}].",
                ],
                inferences=[
                    f"Placeholder inference for {spec.label}; connect a multimodal provider to populate real findings."
                ],
                confidence=0.1,
            )
        analysis.validate()
        return analysis


class _BaseRemoteAnalyzer(MultimodalAnalyzer):
    def __init__(self, provider: str, model: str):
        self._provider = provider
        self._model = model

    @property
    def provenance(self) -> dict[str, str]:
        return {"provider": self._provider, "model": self._model, "mode": "real"}

    @categorized("global_analysis")
    def analyze(
        self,
        metadata: VideoMetadata,
        frames: list[SampledFrame],
        scene_context: SceneContext | None = None,
    ) -> AnalysisReport:
        if not frames:
            raise PrometheusError("Cannot analyze an empty frame set")
        return self._generate_with_retries(
            lambda: self._call_model(metadata, frames, scene_context),
            lambda raw: self._parse_report(raw, metadata, frames),
        )

    @categorized("scene_analysis")
    def analyze_scene(
        self, metadata: VideoMetadata, scene: Scene, frames: list[SampledFrame]
    ) -> SceneAnalysis:
        if not frames:
            raise PrometheusError(f"Cannot analyze scene {scene.index} without frames")
        return self._generate_with_retries(
            lambda: self._call_scene_model(metadata, scene, frames),
            lambda raw: self._parse_scene_report(raw, scene),
        )

    def _generate_with_retries(
        self, call: Callable[[], str], parse: Callable[[str], Any]
    ) -> Any:
        last_error: Exception | None = None
        last_error_was_output = False
        for attempt in range(MAX_RETRIES + 1):
            try:
                with perf_attempt(attempt + 1):
                    raw = call()
                    with stage("response_validation"):
                        return parse(raw)
            except ModelOutputError as exc:
                last_error = exc
                last_error_was_output = True
            except PrometheusError:
                raise
            except Exception as exc:
                if not _is_retryable(exc):
                    raise _wrap_api_error(self._provider, exc) from exc
                last_error = exc
                last_error_was_output = False
            if attempt < MAX_RETRIES:
                seconds = BACKOFF_BASE_SECONDS * (2**attempt)
                with perf_attempt(attempt + 1):
                    retry_wait(seconds)
                    with stage("ai_retry_wait"):
                        time.sleep(seconds)
        if last_error_was_output:
            raise PrometheusError(
                f"{self._provider} returned unusable analysis output after {MAX_RETRIES + 1} attempts: "
                f"{last_error}"
            )
        raise PrometheusError(
            f"{self._provider} API kept failing after {MAX_RETRIES + 1} attempts "
            f"(rate limit or server error): {last_error}"
        )

    def _call_model(
        self,
        metadata: VideoMetadata,
        frames: list[SampledFrame],
        scene_context: SceneContext | None,
    ) -> str:
        raise NotImplementedError

    def _call_scene_model(
        self, metadata: VideoMetadata, scene: Scene, frames: list[SampledFrame]
    ) -> str:
        raise NotImplementedError

    def _parse_report(
        self, raw: str, metadata: VideoMetadata, frames: list[SampledFrame]
    ) -> AnalysisReport:
        data = self._load_json(raw)
        try:
            report = AnalysisReport.from_dict(data)
        except PrometheusError as exc:
            raise ModelOutputError(
                f"{self._provider} returned an invalid analysis structure: {exc}"
            ) from exc
        if all(not f.observations and not f.inferences for f in report.categories.values()):
            raise ModelOutputError(
                f"{self._provider} returned JSON but every category was empty; refusing to save an empty analysis"
            )
        report.video_metadata = metadata.to_dict()
        report.frames = [f.to_dict() for f in frames]
        report.analyzer = self.provenance
        try:
            report.validate()
        except PrometheusError as exc:
            raise ModelOutputError(
                f"{self._provider} returned an invalid analysis structure: {exc}"
            ) from exc
        return report

    def _parse_scene_report(self, raw: str, scene: Scene) -> SceneAnalysis:
        data = self._load_json(raw)
        try:
            analysis = SceneAnalysis.from_dict(data, scene)
        except PrometheusError as exc:
            raise ModelOutputError(
                f"{self._provider} returned an invalid scene analysis structure: {exc}"
            ) from exc
        analysis.analyzer = self.provenance
        try:
            analysis.validate()
        except PrometheusError as exc:
            raise ModelOutputError(
                f"{self._provider} returned an invalid scene analysis structure: {exc}"
            ) from exc
        return analysis

    @timed("response_parsing")
    def _load_json(self, raw: str) -> Any:
        if not raw or not raw.strip():
            raise ModelOutputError(
                f"{self._provider} returned no content for the analysis request "
                "(the response may have been blocked or empty)"
            )
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelOutputError(
                f"{self._provider} returned malformed JSON: {exc}. First 200 chars: {raw[:200]!r}"
            ) from exc

    def _user_instruction(
        self,
        metadata: VideoMetadata,
        frames: list[SampledFrame],
        scene_context: SceneContext | None,
    ) -> str:
        lines = [
            "Analyze this AI-generated video using the attached frames.",
            f"Video metadata: {metadata.width}x{metadata.height}, {metadata.fps} fps, "
            f"{metadata.duration:.2f} seconds, codec {metadata.codec}.",
            "Frames are attached in chronological order:",
        ]
        for frame in frames:
            lines.append(f"- Frame {frame.index}: t={frame.timestamp:.3f}s")
        if scene_context:
            lines.append("")
            lines.append(
                "The video has been segmented into scenes. Timeline with per-scene descriptions:"
            )
            for scene_info in scene_context:
                lines.append(
                    f"- Scene {scene_info['index']}: {scene_info['start']}s-{scene_info['end']}s "
                    f"— {scene_info.get('description', '')}"
                )
            lines.append(
                "Identify which characteristics are shared across scenes (style, palette, "
                "lighting, treatment) and reflect them as the global characteristics."
            )
        cv_brief = getattr(metadata, "_cv_grounding_brief", None)
        if isinstance(cv_brief, str) and cv_brief.strip():
            lines.append("")
            lines.append(cv_brief.strip())
        lines.append("")
        lines.append("Respond with a single JSON object following the schema from the system prompt.")
        return "\n".join(lines)

    def _scene_instruction(
        self, metadata: VideoMetadata, scene: Scene, frames: list[SampledFrame]
    ) -> str:
        lines = [
            f"Analyze scene {scene.index} (from t={scene.start:.2f}s to t={scene.end:.2f}s) "
            "of an AI-generated video, using the attached frames.",
            f"Scene duration: {scene.duration:.2f} seconds. "
            f"Full video: {metadata.width}x{metadata.height}, {metadata.fps} fps, {metadata.duration:.2f}s.",
            "Frames are attached in chronological order:",
        ]
        for frame in frames:
            lines.append(f"- Frame {frame.index}: t={frame.timestamp:.3f}s")
        lines.append("")
        lines.append("Respond with a single JSON object following the schema from the system prompt.")
        return "\n".join(lines)


class OpenAIAnalyzer(_BaseRemoteAnalyzer):
    def __init__(self, model: str = "gpt-4o", api_key: str | None = None, client: Any | None = None):
        super().__init__(provider="openai", model=model)
        self._api_client = client or self._build_client(api_key)

    @staticmethod
    def _build_client(api_key: str | None) -> Any:
        try:
            import openai
        except ImportError as exc:
            raise PrometheusError(
                "The 'openai' package is required for the openai provider: pip install openai"
            ) from exc
        resolved_key = api_key or _resolve_api_key(("PROMETHEUS_OPENAI_API_KEY", "OPENAI_API_KEY"), "openai")
        return openai.OpenAI(api_key=resolved_key, timeout=120.0)

    def _call_model(
        self,
        metadata: VideoMetadata,
        frames: list[SampledFrame],
        scene_context: SceneContext | None,
    ) -> str:
        user_content: list[dict] = [
            {"type": "text", "text": self._user_instruction(metadata, frames, scene_context)}
        ]
        for frame in frames:
            user_content.append(self._image_content(frame.path))
        with ai_call():
            response = self._api_client.chat.completions.create(
                model=self._model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            )
        return response.choices[0].message.content or ""

    def _call_scene_model(
        self, metadata: VideoMetadata, scene: Scene, frames: list[SampledFrame]
    ) -> str:
        user_content: list[dict] = [
            {"type": "text", "text": self._scene_instruction(metadata, scene, frames)}
        ]
        for frame in frames:
            user_content.append(self._image_content(frame.path))
        with ai_call():
            response = self._api_client.chat.completions.create(
                model=self._model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SCENE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            )
        return response.choices[0].message.content or ""

    @staticmethod
    @timed("frame_serialization")
    def _image_content(path: Path) -> dict:
        encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        media_type = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{encoded}"},
        }


class GeminiAnalyzer(_BaseRemoteAnalyzer):
    def __init__(self, model: str = "gemini-flash-lite-latest", api_key: str | None = None, client: Any | None = None):
        super().__init__(provider="gemini", model=model)
        self._api_client = client or self._build_client(api_key)

    @staticmethod
    def _build_client(api_key: str | None) -> Any:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise PrometheusError(
                "The 'google-genai' package is required for the gemini provider: pip install google-genai"
            ) from exc
        resolved_key = api_key or _resolve_api_key(
            ("PROMETHEUS_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"), "gemini"
        )
        return genai.Client(
            api_key=resolved_key,
            http_options=types.HttpOptions(timeout=120_000),
        )

    def _call_model(
        self,
        metadata: VideoMetadata,
        frames: list[SampledFrame],
        scene_context: SceneContext | None,
    ) -> str:
        from google.genai import types

        parts: list[Any] = [
            types.Part.from_text(text=self._user_instruction(metadata, frames, scene_context))
        ]
        for frame in frames:
            parts.append(self._image_part(frame.path))
        with ai_call():
            response = self._api_client.models.generate_content(
                model=self._model,
                contents=parts,
                config=self._config(SYSTEM_PROMPT),
            )
        return self._extract_text(response)

    def _call_scene_model(
        self, metadata: VideoMetadata, scene: Scene, frames: list[SampledFrame]
    ) -> str:
        from google.genai import types

        parts: list[Any] = [
            types.Part.from_text(text=self._scene_instruction(metadata, scene, frames))
        ]
        for frame in frames:
            parts.append(self._image_part(frame.path))
        with ai_call():
            response = self._api_client.models.generate_content(
                model=self._model,
                contents=parts,
                config=self._config(SCENE_SYSTEM_PROMPT),
            )
        return self._extract_text(response)

    @staticmethod
    def _config(system_prompt: str) -> Any:
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            temperature=0.2,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    @staticmethod
    @timed("frame_serialization")
    def _image_part(path: Path) -> Any:
        from google.genai import types

        data = Path(path).read_bytes()
        media_type = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        return types.Part.from_bytes(data=data, mime_type=media_type)

    @staticmethod
    @timed("response_parsing")
    def _extract_text(response: Any) -> str:
        try:
            text = getattr(response, "text", None)
        except Exception:
            text = None
        if text:
            return text
        reason = "unknown"
        candidates = getattr(response, "candidates", None)
        if candidates:
            reason = str(getattr(candidates[0], "finish_reason", "unknown"))
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None:
            reason += f"; prompt feedback: {feedback}"
        raise ModelOutputError(f"Gemini returned no text content (finish reason: {reason})")


def _resolve_api_key(env_names: tuple[str, ...], provider: str) -> str:
    for name in env_names:
        value = os.environ.get(name)
        if value:
            return value
    raise PrometheusError(
        f"No API key found for the {provider} provider. "
        f"Set one of these environment variables: {', '.join(env_names)}. "
        "The pipeline will not silently fall back to mock analysis."
    )


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in RETRYABLE_STATUS_CODES:
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status in RETRYABLE_STATUS_CODES


def _wrap_api_error(provider: str, exc: Exception) -> PrometheusError:
    message = str(exc) or exc.__class__.__name__
    return PrometheusError(f"{provider} API request failed: {message}")


def create_analyzer(config: AnalyzerConfig) -> MultimodalAnalyzer:
    if config.provider == "mock":
        return MockAnalyzer()
    if config.provider == "openai":
        return OpenAIAnalyzer(model=config.resolved_model())
    if config.provider == "gemini":
        return GeminiAnalyzer(model=config.resolved_model())
    raise PrometheusError(f"Unknown analyzer provider: {config.provider}")


def _schema_skeleton() -> str:
    example = {key: {"observations": ["..."], "inferences": ["..."], "confidence": 0.0} for key in (s.key for s in CATEGORIES)}
    return json.dumps({"summary": "...", "categories": example}, indent=2)


def _scene_schema_skeleton() -> str:
    example = {key: {"observations": ["..."], "inferences": ["..."], "confidence": 0.0} for key in SCENE_CATEGORY_KEYS}
    return json.dumps({"description": "...", "categories": example}, indent=2)


_RULES = """Rules:
- Every OBSERVATION must be prefixed with the literal tag "OBSERVATION" and every INFERENCE with
  "INFERENCE", and placed in the matching JSON list. Observations are direct, objective visual
  evidence visible in the frames; reference frame timestamps (e.g. "at t=1.5s").
  Never speculate in observations. Inferences are interpretations and creative deductions.
- UNCERTAINTY: never claim that an inferred camera, lens, model, seed, prompt or generation
  parameter is a known fact. Mark interpretive conclusions with hedged language such as
  "apparent", "likely", "suggests". Treat every generation parameter as a reconstruction
  hypothesis, not a measurement.
- FORBIDDEN CLAIMS: never state an exact AI model name or version, the exact original prompt
  text, a seed value, or hidden generation parameters (steps, CFG scale, sampler, scheduler).
  If a style resembles a known model family, mention it only as a reconstruction hypothesis.
- CONCRETENESS: every inference must contain at least one concrete, reproducible detail — a
  position, count, direction, duration, angle, color family, light direction, or motion path.
  Never substitute vague adjectives for description. Banned vague words: beautiful, stunning,
  gorgeous, amazing, captivating, breathtaking, incredible, nice, high-quality, visually
  appealing. Replace each with a measurable visual fact a creator could reproduce.
- Phrase inferences so they read as reconstruction guidance where possible (e.g. "shot with an
  apparent slow dolly-in, wide 24mm feel") rather than detached commentary.
- confidence is a number between 0.0 and 1.0 estimating how certain the category analysis is.
- If a category has no visible evidence (e.g. no typography), leave it empty with confidence 0.0.
"""

SYSTEM_PROMPT = f"""You are a video reverse-engineering expert. You receive frames sampled from an
AI-generated video, plus its technical metadata. Your goal is NOT to recover the exact original
prompt (impossible), but to infer the creative recipe that could reproduce the video's visual
characteristics — not merely describe its content.

{_RULES}
- Transitions: compare consecutive frames to deduce cut/fade patterns.
- Motion: reason from differences between chronological frames and the video duration.
- DEPTH: describe spatial organization — foreground, midground and background layers, and
  whether staging reads flat (graphic) or deep (photographic), including parallax cues.
- EDITING RHYTHM: use the scene timeline durations to characterize pacing — shot-length range,
  cut frequency, and whether pacing accelerates, holds steady, or breathes. For a single
  continuous shot, say so and describe its internal pacing instead.
- SIGNATURE ELEMENTS: identify 3-5 distinctive signature elements that make this video
  recognizable (recurring motifs, palette anchors, signature moves or transitions).
- PERSISTENCE: separate what is persistent across all scenes from what varies scene to scene.
  Lead the summary with the persistent visual language and signature elements, then note
  notable variations.
- Shared characteristics: when a scene timeline is provided, identify which characteristics
  are consistent across scenes (style, palette, lighting, treatment) and treat them as the
  global characteristics; note scene-to-scene variation in the relevant categories.

Analyze these categories:
{chr(10).join(f"- {spec.key}: {spec.label} — {spec.description}" for spec in CATEGORIES)}

Respond with JSON only, matching exactly this structure:
{_schema_skeleton()}
"""

SCENE_SYSTEM_PROMPT = f"""You are a video reverse-engineering expert. You receive frames sampled from
ONE scene (a continuous segment between two cuts) of an AI-generated video. Your goal is to infer
the creative recipe that could reproduce THIS SCENE's visual characteristics — not merely
describe its content.

{_RULES}
- Motion: reason from differences between chronological frames and the scene duration.
- The description is one or two sentences capturing what the scene shows and how it is staged.

Analyze these scene categories:
{chr(10).join(f"- {spec.key}: {spec.label} — {spec.description}" for spec in SCENE_CATEGORIES)}

Respond with JSON only, matching exactly this structure:
{_scene_schema_skeleton()}
"""
