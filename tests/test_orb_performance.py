"""Local fixtures + mocked SDK transports only; no real AI, RPC or DB services."""
from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from fakes import FakeAPIError, FakeClient, FakeResponse, VALID_GLOBAL_JSON, VALID_SCENE_JSON
from prometheus import performance as perf
from prometheus.analysis.analyzer import GeminiAnalyzer
from prometheus.analysis.orb_ai import OrbAIService
from prometheus.api.app import create_app
from prometheus.api.jobs import JobManager
from test_orb_stage3 import _client, _png_bytes, _result
from test_orb_credits import setup, grant, sign_in  # Disposable ledger/wallet/RPC fixture.


def events(caplog, name="orb_perf_summary"):
    return [json.loads(r.getMessage().split(" ", 1)[1]) for r in caplog.records
            if r.name == perf._LOG.name and r.getMessage().startswith(name + " ")]


def summary(caplog, job_id):
    deadline = time.perf_counter() + 5
    while time.perf_counter() < deadline:
        found = [event for event in events(caplog) if event["job_id"] == job_id and event["status"] != "reused"]
        if found:
            return found[0]
        time.sleep(.01)
    raise AssertionError("Worker timing summary was not emitted")


def service(raw=None, failure=None):
    sdk = FakeClient(lambda _: failure if failure else FakeResponse(json.dumps(raw or {
        "prompt": "private-result-sentinel", "enhanced_prompt": "private-result-sentinel",
        "visual_analysis": {"subject_and_scene": "private-subject", "composition": "center", "lighting": "soft"},
        "refinements": []})))
    result = OrbAIService.__new__(OrbAIService)
    result.provider = "gemini"
    result.model = "test-model"
    result.analyzer = GeminiAnalyzer(client=sdk)
    return result, sdk


def test_monotonic_lifecycle_and_allowlisted_observations(caplog):
    now = [10.0]
    trace = perf.JobTiming("decode_image", clock=lambda: now[0])
    with perf.bind(trace):
        now[0] = 11
        perf.observe("request_parsed")
        now[0] = 12
        perf.observe("enqueue")
        now[0] = 15
        perf.observe("worker_start")
        perf.metric("prompt", "private-prompt")
        perf.metric("width", 32)
        perf.metric("width", 32)  # Repeated probes do not double dimensions.
        perf.metric("input_bytes", float("nan"))
        now[0] = 18
        perf.observe("finish", "complete")
        perf.observe("finish", "private-prompt")
    event = events(caplog)[0]
    assert event["total_ms"] == 8000
    assert event["queue_ms"] == 3000
    assert event["processing_ms"] == 3000
    assert event["worker_start_ms"] == 5000
    assert event["width"] == 32
    assert len(events(caplog)) == 1
    assert "private-prompt" not in json.dumps(event)
    assert "input_bytes" not in event


def test_one_worker_queue_and_context_are_isolated(caplog):
    now = [0.0]
    manager = JobManager(max_workers=1)
    started, release, second_done = threading.Event(), threading.Event(), threading.Event()
    trace1 = perf.JobTiming("decode_image", clock=lambda: now[0])
    with perf.bind(trace1):
        first = manager.create("private-first.png")
    def work1():
        assert perf.current() is trace1
        perf.metric("width", 100)
        started.set()
        assert release.wait(5)
    now[0] = 1
    manager.submit(first.id, work1)
    assert started.wait(2)
    now[0] = 3
    trace2 = perf.JobTiming("enhance", clock=lambda: now[0])
    with perf.bind(trace2):
        second = manager.create("private-second")
    def work2():
        assert perf.current() is trace2
        perf.metric("width", 200)
        now[0] = 12
        second_done.set()
    now[0] = 4
    manager.submit(second.id, work2)
    assert manager.public_info(second)["queue_position"] == 0
    assert "timing" not in manager.public_info(second)
    now[0] = 10
    release.set()
    assert second_done.wait(2)
    first_summary, second_summary = summary(caplog, first.id), summary(caplog, second.id)
    assert first_summary["width"] == 100
    assert second_summary["width"] == 200
    assert second_summary["queue_ms"] == 6000
    assert second_summary["processing_ms"] == 2000
    assert second_summary["total_ms"] == 9000
    manager._executor.shutdown(wait=True)
    assert perf.current() is None


@pytest.mark.parametrize("operation", ["decode", "compose", "enhance"])
def test_api_image_and_enhance_timings_do_not_change_results(tmp_path, monkeypatch, caplog, operation):
    ai, sdk = service()
    client = _client(tmp_path, monkeypatch, ai)
    if operation == "enhance":
        response = client.post("/api/orb/enhance", json={"prompt": "private-user-prompt-sentinel"})
    else:
        response = client.post(f"/api/orb/{operation}/file", files={"file": ("private-name.png", _png_bytes(), "image/png")})
    assert response.status_code == 202
    assert set(response.json()) == {"job_id"}
    job_id = response.json()["job_id"]
    result = _result(client, job_id)
    assert result["prompt"] == "private-result-sentinel"
    expected = {"job_id", "operation", "prompt", "provider"}
    expected |= {"original_prompt", "output", "style", "detail"} if operation == "enhance" else {"image", "visual_analysis", "refinements", "notice"}
    if operation != "enhance":
        expected.add("opencv_telemetry")
        assert result["opencv_telemetry"]["media_kind"] == "image"
        assert result["opencv_telemetry"]["opencv_version"]
    assert set(result) == expected
    event = summary(caplog, job_id)
    assert event["operation"] == ("enhance" if operation == "enhance" else operation + "_image")
    assert event["ai_calls"] == sdk.models.calls == 1
    assert event["ai_retries"] == 0
    for key in ["queue_ms", "processing_ms", "authorization_ms", "response_parsing_ms", "response_validation_ms", "result_persistence_ms", "total_ms"]:
        assert event[key] >= 0
    if operation != "enhance":
        assert event["input_bytes"] == len(_png_bytes())
        assert (event["width"], event["height"]) == (32, 24)
        assert event["file_validation_ms"] >= 0
        assert event["frame_serialization_ms"] >= 0
    assert event["ai_total_ms"] == event["ai_longest_ms"] == event["ai_success_average_ms"]
    records = events(caplog, "orb_perf") + events(caplog, "orb_perf_request") + events(caplog)
    assert "private-" not in json.dumps(records)
    assert "test-key" not in json.dumps(records)


@pytest.mark.parametrize("operation", ["decode", "compose"])
def test_real_video_tools_with_mocked_ai_have_exact_counts(tmp_path, monkeypatch, caplog, synthetic_video, operation):
    import prometheus.pipeline as pipeline
    sdk = FakeClient(lambda _: FakeResponse(VALID_SCENE_JSON if "ONE scene" in sdk.models.last_kwargs["config"].system_instruction else VALID_GLOBAL_JSON))
    monkeypatch.setattr(pipeline, "create_analyzer", lambda _: GeminiAnalyzer(client=sdk))
    ai, compose_sdk = service()
    client = _client(tmp_path, monkeypatch, ai)
    response = client.post(f"/api/orb/{operation}/file", files={"file": ("private-video.mp4", synthetic_video.read_bytes(), "video/mp4")})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    result = _result(client, job_id)
    event = summary(caplog, job_id)
    assert event["operation"] == operation + "_video"
    assert event["ffprobe_launches"] == 1  # Reuse authoritative unchanged-upload metadata.
    assert event["video_duration_s"] == result["video"]["duration"] == 4
    assert event["width"] == 320 and event["height"] == 240
    assert event["scene_count"] == len(result["scenes"])
    assert event["frames"] == event["scene_frames"] + event["global_frames"]
    assert event["ffmpeg_launches"] == event["unique_extracted_frames"] + 1
    assert event["unique_extracted_frames"] + event.get("frame_cache_hits", 0) == event["frames"]
    assert event["ai_calls"] == event["scene_count"] + 1 + (operation == "compose")
    assert sdk.models.calls == event["scene_count"] + 1
    assert compose_sdk.models.calls == (operation == "compose")
    for key in ["ffprobe_ms", "ffprobe_process_ms", "scene_detection_ms", "frame_extraction_ms", "ffmpeg_ms", "frame_serialization_ms", "artifact_persistence_ms"]:
        assert event[key] > 0
    requests = [r for r in events(caplog, "orb_perf") if r.get("stage") == "ai_request"]
    assert [r["sequence"] for r in requests] == list(range(1, event["ai_calls"] + 1))
    assert {r["purpose"] for r in requests} == ({"scene_analysis", "global_analysis", "compose_synthesis"} if operation == "compose" else {"scene_analysis", "global_analysis"})
    assert "private-video" not in json.dumps(events(caplog))


def test_provider_retries_and_parse_retries_are_counted_without_private_content(tmp_path, monkeypatch, caplog):
    waits = []
    monkeypatch.setattr("prometheus.analysis.analyzer.time.sleep", lambda delay: waits.append(delay))
    sdk = FakeClient(lambda n: FakeAPIError(503) if n == 1 else FakeResponse("private-invalid-output" if n == 2 else json.dumps({"enhanced_prompt": "private-result"})))
    ai, _ = service()
    ai.analyzer = GeminiAnalyzer(client=sdk)
    trace = perf.JobTiming("enhance")
    with perf.bind(trace):
        assert ai.enhance("private-user-prompt", "image", "", "balanced") == "private-result"
        trace.finish("complete")
    event = events(caplog)[0]
    assert event["ai_calls"] == 3 and event["ai_retries"] == 2
    assert waits == [2, 4]  # Existing policy unchanged.
    calls = [r for r in events(caplog, "orb_perf") if r["stage"] == "ai_request"]
    assert [r["attempt"] for r in calls] == [1, 2, 3]
    assert [r["success"] for r in calls] == [False, True, True]
    assert [r["planned_delay_ms"] for r in events(caplog, "orb_perf") if r["stage"] == "ai_retry_wait"] == [2000, 4000]
    assert "private-" not in json.dumps(events(caplog) + events(caplog, "orb_perf"))


def test_failed_job_and_invalid_upload_emit_timings(tmp_path, monkeypatch, caplog):
    ai, _ = service(failure=FakeAPIError(400))
    client = _client(tmp_path, monkeypatch, ai)
    failed = client.post("/api/orb/enhance", json={"prompt": "private-user-prompt"})
    event = summary(caplog, failed.json()["job_id"])
    assert event["status"] == "error" and event["ai_calls"] == 1
    assert event["total_ms"] >= event["ai_total_ms"]
    assert client.post("/api/orb/decode/file", files={"file": ("bad.png", b"bad image", "image/png")}).status_code == 422
    invalid = [r for r in events(caplog) if r["status"] == "request_error"][-1]
    assert invalid["file_validation_ms"] >= 0 and invalid["upload_save_ms"] >= 0


@pytest.mark.parametrize("fail_ai", [False, True])
@pytest.mark.parametrize("fail_logging", [False, True])
def test_paid_settlement_idempotency_and_log_failure_are_unchanged(setup, tmp_path, monkeypatch, caplog, fail_ai, fail_logging):
    ledger, wallet, receiver, rpc = setup
    grant(ledger, wallet, receiver, rpc, credits=1)
    _, _, signed = sign_in(ledger, wallet)
    monkeypatch.setenv("ORB_AI_LOCAL_TESTING", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-placeholder")
    monkeypatch.delenv("ORB_ENABLE_NIMIQ_PAYMENTS", raising=False)
    ai, sdk = service(failure=FakeAPIError(400) if fail_ai else None)
    if fail_logging:
        def broken_logger(*args, **kwargs):
            raise RuntimeError("logging unavailable")
        monkeypatch.setattr(perf._LOG, "info", broken_logger)
    app = create_app(provider="gemini", output_dir=tmp_path / "out", upload_dir=tmp_path / "uploads", orb_ai_service=ai, orb_credit_service=ledger)
    with TestClient(app, base_url="http://localhost") as client:
        headers = {"Origin": "http://localhost", "Authorization": "Bearer " + signed["token"], "X-Orb-Idempotency-Key": "timing-safe-request-000000000001"}
        response = client.post("/api/orb/decode/file", files={"file": ("private.png", _png_bytes(), "image/png")}, headers=headers)
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        deadline = time.perf_counter() + 5
        while time.perf_counter() < deadline:
            state = client.get(f"/api/jobs/{job_id}", headers=headers).json()["state"]
            if state != "processing": break
            time.sleep(.01)
        assert state == ("error" if fail_ai else "complete")
        balance = ledger.balance(wallet.address.lower())
        assert balance["consumed"] == (0 if fail_ai else 1)
        assert balance["available"] == (1 if fail_ai else 0)
        assert balance["reserved"] == 0
        duplicate = client.post("/api/orb/decode/file", files={"file": ("private.png", _png_bytes(), "image/png")}, headers=headers)
        assert duplicate.json()["job_id"] == job_id
        assert sdk.models.calls == 1
        assert ledger.balance(wallet.address.lower()) == balance
        if not fail_logging:
            event = summary(caplog, job_id)
            assert event["paid"] == 1 and event["credit_settlement_ms"] >= 0 and event["file_hash_ms"] >= 0
            if not fail_ai: assert event["result_persistence_ms"] >= 0
            assert "private" not in json.dumps(events(caplog) + events(caplog, "orb_perf"))
