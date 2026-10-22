"""Generated local media and mocked provider only; never live AI/RPC/Postgres."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fakes import FakeAPIError, VALID_SCENE_JSON
from prometheus import performance as perf
from prometheus.analysis.analyzer import GeminiAnalyzer, MockAnalyzer
from prometheus.analysis.prompt_builder import build_scene_reconstruction_prompt
from prometheus.config import PrometheusConfig, SamplingConfig
from prometheus.errors import PrometheusError
from prometheus.pipeline import PrometheusPipeline
from prometheus.storage import prepare_scene_directory, save_scene_analysis, save_scene_prompt
from prometheus.video.probe import ValidatedVideo, VideoMetadata, probe_video, video_identity
from prometheus.video.sampler import FrameSampler, SampledFrame, canonical_timestamp, uniform_timestamps
from prometheus.video.segmenter import Scene
from test_orb_credits import setup, grant, sign_in
from test_orb_stage3 import FakeAI, _result


def metadata(path="test.mp4"):
    return VideoMetadata(path, "mp4", 12, 320, 240, 24, "h264", "yuv420p", 1, 288)


def fake_frames(video, start, end, count, output_dir, **kwargs):
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, timestamp in enumerate(uniform_timestamps(start, end, count)):
        path = output_dir / f"{i}.jpg"
        path.write_bytes(canonical_timestamp(timestamp).encode())
        frames.append(SampledFrame(i, timestamp, path))
    return frames


class RecordingAnalyzer(MockAnalyzer):
    def __init__(self, delay=.02):
        self.delay = delay
        self.active = self.peak = 0
        self.lock = threading.Lock()
        self.finished = []
        self.inputs = {}
        self.global_input = None
        self.instructions = GeminiAnalyzer(client=object())

    def analyze_scene(self, video, scene, frames):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            assert scene.index not in self.inputs
            self.inputs[scene.index] = (
                self.instructions._scene_instruction(video, scene, frames),
                [(f.index, f.timestamp, hashlib.sha256(f.path.read_bytes()).hexdigest()) for f in frames],
            )
        try:
            with perf.ai_call():
                time.sleep(self.delay(scene.index) if callable(self.delay) else self.delay)
            return super().analyze_scene(video, scene, frames)
        finally:
            with self.lock:
                self.finished.append(scene.index)
                self.active -= 1

    def analyze(self, video, frames, scene_context=None):
        assert self.active == 0  # Global depends on all scene results.
        self.global_input = (
            self.instructions._user_instruction(video, frames, scene_context),
            [(f.index, f.timestamp, hashlib.sha256(f.path.read_bytes()).hexdigest()) for f in frames],
        )
        return super().analyze(video, frames, scene_context)


def sequential_scenes(pipeline, video, scenes, run_dir):
    """Reference to the pre-Phase-1 serial scene implementation, without cache."""
    summaries = []
    for scene in scenes:
        directory = prepare_scene_directory(run_dir, scene)
        frames = pipeline.sampler.sample_range(video, scene.start, scene.end,
                                              pipeline.config.segmentation.frames_per_scene, directory / "frames")
        analysis = pipeline.analyzer.analyze_scene(video, scene, frames)
        analysis_path = save_scene_analysis(directory, analysis)
        prompt_path, _ = save_scene_prompt(directory, build_scene_reconstruction_prompt(analysis))
        info = scene.to_dict()
        info.update(description=analysis.description, frames=[f.to_dict() for f in frames],
                    analysis_file=str(analysis_path.relative_to(run_dir)),
                    prompt_file=str(prompt_path.relative_to(run_dir)))
        summaries.append(info)
    return summaries


@pytest.mark.parametrize("count", [1, 2, 12])
def test_bounded_calls_keep_original_order_and_inputs(tmp_path, monkeypatch, count):
    analyzer = RecordingAnalyzer(lambda index: .07 if index % 2 == 0 else .005)
    pipeline = PrometheusPipeline(analyzer=analyzer)
    monkeypatch.setattr(pipeline.sampler, "sample_range", fake_frames)
    scenes = [Scene(i, float(i), float(i + 1)) for i in range(count)]
    trace = perf.JobTiming("decode_video")
    with perf.bind(trace):
        optimized = pipeline._analyze_scenes(metadata(), scenes, tmp_path / "parallel", lambda _: None, {})
    reference = RecordingAnalyzer(delay=0)
    pipeline.analyzer = reference
    original = sequential_scenes(pipeline, metadata(), scenes, tmp_path / "serial")
    assert optimized == original
    assert analyzer.inputs == reference.inputs
    assert analyzer.peak == min(count, 2)
    assert analyzer.active == 0 and sorted(analyzer.finished) == list(range(count))
    assert trace.ai_peak == min(count, 2) and trace.values["ai_calls"] == count
    assert trace.values["scene_ai_wall_ms"] > 0
    if count > 1:
        assert analyzer.finished.index(1) < analyzer.finished.index(0)


def test_four_half_second_calls_take_two_waves(tmp_path, monkeypatch):
    pipeline = PrometheusPipeline(analyzer=RecordingAnalyzer(.5))
    monkeypatch.setattr(pipeline.sampler, "sample_range", fake_frames)
    scenes = [Scene(i, i, i + 1) for i in range(4)]
    start = time.perf_counter()
    sequential_scenes(pipeline, metadata(), scenes, tmp_path / "serial")
    sequential_ms = (time.perf_counter() - start) * 1000
    pipeline.analyzer = RecordingAnalyzer(.5)
    start = time.perf_counter()
    trace = perf.JobTiming("decode_video")
    with perf.bind(trace):
        pipeline._analyze_scenes(metadata(), scenes, tmp_path / "parallel", lambda _: None, {})
    parallel_ms = (time.perf_counter() - start) * 1000
    assert sequential_ms >= 1900
    assert 900 <= trace.values["scene_ai_wall_ms"] < 1600
    assert parallel_ms < sequential_ms * .85
    print(f"Mock four-call benchmark: sequential={sequential_ms:.1f}ms parallel={parallel_ms:.1f}ms scene_ai_wall={trace.values['scene_ai_wall_ms']:.1f}ms")


class RetryAnalyzer(GeminiAnalyzer):
    def __init__(self, failure=None):
        super().__init__(client=object())
        self.calls = {}
        self.lock = threading.Lock()
        self.active = 0
        self.failure = failure

    def _call_scene_model(self, video, scene, frames):
        with self.lock:
            self.calls[scene.index] = self.calls.get(scene.index, 0) + 1
            number = self.calls[scene.index]
            self.active += 1
        try:
            with perf.ai_call():
                time.sleep(.02 if scene.index == 1 else .005)
                if scene.index == 0:
                    if self.failure:
                        raise self.failure
                    if number == 1:
                        raise FakeAPIError(503)
                return VALID_SCENE_JSON
        finally:
            with self.lock:
                self.active -= 1


def test_retries_remain_per_scene_and_timing_context_survives_threads(tmp_path, monkeypatch):
    waits = []
    original_sleep = time.sleep
    def sleep(seconds):
        if seconds >= 2:
            waits.append(seconds)
            original_sleep(.01)
        else:
            original_sleep(seconds)
    monkeypatch.setattr("prometheus.analysis.analyzer.time.sleep", sleep)
    analyzer = RetryAnalyzer()
    pipeline = PrometheusPipeline(analyzer=analyzer)
    monkeypatch.setattr(pipeline.sampler, "sample_range", fake_frames)
    trace = perf.JobTiming("compose_video")
    with perf.bind(trace):
        results = pipeline._analyze_scenes(metadata(), [Scene(i, i, i + 1) for i in range(4)], tmp_path, lambda _: None)
    assert [s["index"] for s in results] == [0, 1, 2, 3]
    assert analyzer.calls == {0: 2, 1: 1, 2: 1, 3: 1}
    assert waits == [2] and trace.values["ai_retries"] == 1
    assert trace.values["ai_calls"] == 5 and trace.ai_peak == 2


@pytest.mark.parametrize("failure", [FakeAPIError(400), TimeoutError("mock SDK timeout"), KeyboardInterrupt()])
def test_failure_timeout_or_interruption_joins_calls_before_cleanup(tmp_path, monkeypatch, failure):
    analyzer = RetryAnalyzer(failure)
    pipeline = PrometheusPipeline(analyzer=analyzer)
    monkeypatch.setattr(pipeline.sampler, "sample_range", fake_frames)
    expected = KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else PrometheusError
    with pytest.raises(expected):
        pipeline._analyze_scenes(metadata(), [Scene(i, i, i + 1) for i in range(12)], tmp_path, lambda _: None)
    assert analyzer.active == 0
    assert set(analyzer.calls) <= {0, 1}  # No unbounded queued work after first failure.
    assert all(count == 1 for count in analyzer.calls.values())
    assert not list(tmp_path.glob("**/scene.json"))


def test_canonical_dedup_preserves_bytes_order_and_nearby_seeks(tmp_path, monkeypatch):
    import prometheus.video.sampler as module
    launches = []
    def extract(ffmpeg, source, timestamp, destination, image_format, quality):
        launches.append(canonical_timestamp(timestamp))
        destination.write_bytes(canonical_timestamp(timestamp).encode())
    monkeypatch.setattr(module, "extract_frame", extract)
    sampler = FrameSampler(SamplingConfig())
    cache = {}
    times = [1.25, 1.25000000001, 1.251, 1.25]
    (tmp_path / "first").mkdir()
    frames = sampler._extract_all(metadata(), times, tmp_path / "first", cache)
    assert launches == ["1.250", "1.251"]
    assert [f.timestamp for f in frames] == times
    assert [f.index for f in frames] == list(range(4))
    assert [f.path.read_bytes() for f in frames] == [b"1.250", b"1.250", b"1.251", b"1.250"]
    (tmp_path / "second").mkdir()
    sampler._extract_all(metadata(), times[:1], tmp_path / "second", {})
    assert len(launches) == 3  # No cache shared across runs.


@pytest.mark.parametrize("fixture,frame_count", [("synthetic_video", 8), ("cut_video", 8), ("cut_video", 4)])
def test_real_frames_and_provider_prompts_match_serial_evidence(tmp_path, request, monkeypatch, fixture, frame_count):
    from types import SimpleNamespace
    # Compare concurrency with the SAME grounding input on both paths. OpenCV
    # integration has its own tests; its addition must not make this baseline
    # compare an ungrounded prompt to a grounded one.
    grounding = "Controlled OpenCV grounding for evidence-equivalence test"
    monkeypatch.setattr("prometheus.pipeline.analyze_video_cv", lambda *args, **kwargs:
                        SimpleNamespace(cv_grounding_brief=grounding, to_dict=lambda: {"test_grounding": grounding}))
    source = request.getfixturevalue(fixture)
    video = probe_video(source)
    config = PrometheusConfig()
    config.sampling.frame_count = frame_count
    analyzer = RecordingAnalyzer(delay=0)
    pipeline = PrometheusPipeline(config=config, analyzer=analyzer)
    scenes = pipeline.segmenter.segment(video)
    original = sequential_scenes(pipeline, video, scenes, tmp_path / "serial")
    original_frames = pipeline.sampler.sample(video, tmp_path / "serial_global")
    setattr(video, "_cv_grounding_brief", grounding)
    analyzer.analyze(video, original_frames, original)
    baseline_input, baseline_global = analyzer.inputs, analyzer.global_input
    optimized = RecordingAnalyzer(delay=0)
    pipeline.analyzer = optimized
    config.output.directory = tmp_path / "optimized"
    trace = perf.JobTiming("decode_video")
    with perf.bind(trace):
        result = pipeline.run(source, validated_video=ValidatedVideo(video, video_identity(source)))
    assert optimized.inputs == baseline_input and optimized.global_input == baseline_global
    assert grounding in optimized.global_input[0]
    assert result.report.scenes == original
    assert [f.timestamp for f in result.frames] == [f.timestamp for f in original_frames]
    expected_hits = 4 if fixture == "cut_video" and frame_count == 4 else 0
    assert trace.values.get("frame_cache_hits", 0) == expected_hits
    assert trace.values["frames"] == len(scenes) * 2 + frame_count
    assert trace.values["unique_extracted_frames"] == trace.values["frames"] - expected_hits


@pytest.mark.parametrize("fixture,frame_count", [("synthetic_video", 8), ("cut_video", 8), ("cut_video", 4)])
def test_generated_video_before_after_benchmark(tmp_path, request, fixture, frame_count):
    source = request.getfixturevalue(fixture)

    class SequentialPipeline(PrometheusPipeline):
        def _analyze_scenes(self, video, scenes, run_dir, notify, extraction_cache=None):
            results = sequential_scenes(self, video, scenes, run_dir)
            perf.metric("scene_frames", sum(len(s["frames"]) for s in results))
            return results

    class DelayAnalyzer(RecordingAnalyzer):
        def analyze(self, video, frames, scene_context=None):
            with perf.ai_call():
                time.sleep(.25)
            return super().analyze(video, frames, scene_context)

    records, results = {}, {}
    for mode, pipeline_type in [("before", SequentialPipeline), ("after", PrometheusPipeline)]:
        config = PrometheusConfig()
        config.sampling.frame_count = frame_count
        config.output.directory = tmp_path / mode
        analyzer = DelayAnalyzer(.5)
        trace = perf.JobTiming("decode_video")
        start = time.perf_counter()
        with perf.bind(trace):
            # Include the existing authoritative upload probe in both totals.
            video = probe_video(source)
            validated = ValidatedVideo(video, video_identity(source))
            pipeline = pipeline_type(config=config, analyzer=analyzer)
            result = pipeline.run(source, validated_video=validated if mode == "after" else None)
        records[mode] = {
            "total_ms": round((time.perf_counter() - start) * 1000, 1),
            "ffprobe_launches": trace.values["ffprobe_launches"],
            "frames": trace.values["frames"],
            "unique_frames": trace.values["unique_extracted_frames"],
            "cache_hits": trace.values.get("frame_cache_hits", 0),
            "ffmpeg_launches": trace.values["ffmpeg_launches"],
            "ai_calls": trace.values["ai_calls"], "peak_ai_concurrency": trace.ai_peak,
            "ai_sum_ms": round(trace.values["ai_total_ms"], 1),
            "scene_ai_wall_ms": round(trace.values.get("scene_ai_wall_ms", 0), 1),
        }
        results[mode] = result
    before, after = records["before"], records["after"]
    assert before["ffprobe_launches"] == 2 and after["ffprobe_launches"] == 1
    assert before["frames"] == after["frames"]
    assert before["ai_calls"] == after["ai_calls"] == len(results["before"].scenes) + 1
    assert before["peak_ai_concurrency"] == 1
    assert after["peak_ai_concurrency"] == min(2, len(results["after"].scenes))
    assert before["ffmpeg_launches"] - after["ffmpeg_launches"] == after["cache_hits"]
    assert results["before"].report.to_dict() == results["after"].report.to_dict()
    assert results["before"].prompt == results["after"].prompt
    print("PHASE1_BENCHMARK " + json.dumps({"fixture": fixture, "global_frame_count": frame_count, **records}, sort_keys=True))


@pytest.mark.parametrize("change", ["none", "modified", "different_path"])
def test_validated_probe_is_reused_only_for_same_unchanged_file(tmp_path, synthetic_video, monkeypatch, change):
    import prometheus.pipeline as module
    source = tmp_path / "source.mp4"
    source.write_bytes(synthetic_video.read_bytes())
    video = probe_video(source)
    validated = ValidatedVideo(video, video_identity(source))
    if change == "modified":
        source.write_bytes(source.read_bytes() + b"\0")
    elif change == "different_path":
        target = tmp_path / "other.mp4"
        target.write_bytes(source.read_bytes())
        source = target
    calls = []
    def probe(path):
        calls.append(path)
        return probe_video(path)
    monkeypatch.setattr(module, "probe_video", probe)
    config = PrometheusConfig()
    config.output.directory = tmp_path / "out"
    PrometheusPipeline(config=config).run(source, validated_video=validated)
    assert len(calls) == (0 if change == "none" else 1)


@pytest.mark.parametrize("operation", ["decode", "compose"])
@pytest.mark.parametrize("fail_scene", [False, True])
def test_paid_video_settles_once_after_all_scenes(setup, tmp_path, synthetic_video, monkeypatch, operation, fail_scene):
    import prometheus.pipeline as module
    from prometheus.api.app import create_app
    ledger, wallet, receiver, rpc = setup
    grant(ledger, wallet, receiver, rpc, credits=1)
    _, _, signed = sign_in(ledger, wallet)
    monkeypatch.setenv("ORB_AI_LOCAL_TESTING", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "test-placeholder")
    monkeypatch.delenv("ORB_ENABLE_NIMIQ_PAYMENTS", raising=False)
    analyzer = RecordingAnalyzer(delay=.02)
    if fail_scene:
        analyzer = RetryAnalyzer(FakeAPIError(400))
    monkeypatch.setattr(module, "create_analyzer", lambda _: analyzer)
    monkeypatch.setattr(module.SceneSegmenter, "segment", lambda _, video: [Scene(0, 0, 2), Scene(1, 2, 4)])
    compose_calls = []
    class OrderedCompose(FakeAI):
        def compose_video(self, analysis):
            assert analyzer.active == 0 and analyzer.global_input is not None
            assert [scene["index"] for scene in analysis["scenes"]] == [0, 1]
            compose_calls.append(analysis)
            return super().compose_video(analysis)
    counts = {"reserve": 0, "settle": 0, "save_result": 0}
    for name in counts:
        original = getattr(ledger, name)
        def counted(*args, _name=name, _original=original, **kwargs):
            # Existing GET recovery may race with worker settlement and safely
            # repeat its idempotent call. Count the worker's one settlement;
            # assert the actual durable balance below for both callers.
            if _name != "settle" or perf.current() is not None:
                counts[_name] += 1
            if _name in {"settle", "save_result"}:
                assert analyzer.active == 0
            return _original(*args, **kwargs)
        monkeypatch.setattr(ledger, name, counted)
    app = create_app(provider="gemini", output_dir=tmp_path / "out", upload_dir=tmp_path / "uploads",
                     orb_ai_service=OrderedCompose(), orb_credit_service=ledger)
    with TestClient(app, base_url="http://localhost") as client:
        headers = {"Origin": "http://localhost", "Authorization": "Bearer " + signed["token"],
                   "X-Orb-Idempotency-Key": "phase-one-video-0000000000000000001"}
        files = {"file": ("video.mp4", synthetic_video.read_bytes(), "video/mp4")}
        response = client.post(f"/api/orb/{operation}/file", files=files, headers=headers)
        assert response.status_code == 202
        job = response.json()["job_id"]
        deadline = time.perf_counter() + 15
        while time.perf_counter() < deadline:
            state = client.get(f"/api/jobs/{job}", headers=headers).json()["state"]
            if state != "processing":
                break
            time.sleep(.01)
        assert state == ("error" if fail_scene else "complete")
        assert counts == {"reserve": 1, "settle": 1, "save_result": 0 if fail_scene else 1}
        assert len(compose_calls) == (1 if operation == "compose" and not fail_scene else 0)
        balance = ledger.balance(wallet.address.lower())
        assert balance["reserved"] == 0 and balance["consumed"] == (0 if fail_scene else 1)
        assert balance["available"] == (1 if fail_scene else 0)
        assert not list((tmp_path / "uploads").iterdir())
        duplicate = client.post(f"/api/orb/{operation}/file", files=files, headers=headers)
        assert duplicate.json()["job_id"] == job
        assert counts["settle"] == 1 and counts["save_result"] == (0 if fail_scene else 1)
        assert ledger.balance(wallet.address.lower()) == balance
