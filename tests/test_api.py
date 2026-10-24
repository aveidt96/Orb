from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import prometheus.api.app as app_module
from prometheus.api.app import create_app
from prometheus.api.jobs import JobManager
from prometheus.api.payments import PaymentConfig, PaymentService
from prometheus.video.tools import VideoToolError


RECIPIENT = "NQ43 HJUE 9G1D 5LQF C752 5T7H EJ9M 4QEM 1CB1"
TX_HASH = "cd" * 32


def _payment_service(tmp_path):
    holder = {}

    def rpc_call(method, params):
        if method == "getLatestBlock":
            return {"data": {"network": "TestAlbatross"}}
        quote = holder["quote"]
        return {"data": {
            "hash": TX_HASH,
            "to": RECIPIENT,
            "value": 1_000_000,
            "recipientData": quote["memo"].encode().hex(),
            "executionResult": True,
            "blockNumber": 123,
            "confirmations": 1,
        }}

    service = PaymentService(
        PaymentConfig(RECIPIENT, 1_000_000, "https://rpc.test.invalid/"),
        tmp_path / "payments.db",
        rpc_call=rpc_call,
    )
    return service, holder


def _verify_for_job(service, holder, job_id):
    quote = service.create_quote(job_id)
    holder["quote"] = quote
    service.verify(quote["id"], TX_HASH)
    return quote


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        provider="mock",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
    )
    return TestClient(app)


def _upload(client, path, name="video.mp4"):
    data = path.read_bytes()
    return client.post("/api/analyze", files={"file": (name, data, "video/mp4")})


def _stage_upload(client, path, name="video.mp4"):
    data = path.read_bytes()
    return client.post("/api/uploads", files={"file": (name, data, "video/mp4")})


def _wait_complete(client, job_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        state = response.json()["state"]
        if state == "complete":
            return
        if state == "error":
            raise AssertionError(f"job failed: {response.json()['error']}")
        time.sleep(0.5)
    raise AssertionError("job did not complete in time")


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["analyzer"]["provider"] == "mock"
    root_response = client.get("/health")
    assert root_response.status_code == 200
    assert root_response.json() == body


def test_ready_confirms_local_upload_prerequisites(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "_verify_video_tool", lambda name: None)
    app = create_app(
        provider="mock",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
    )

    with TestClient(app) as ready_client:
        response = ready_client.get("/api/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_reports_missing_ffmpeg(monkeypatch, tmp_path):
    def missing_ffmpeg(name):
        if name == "ffmpeg":
            raise VideoToolError("ffmpeg executable not found")

    monkeypatch.setattr(app_module, "_verify_video_tool", missing_ffmpeg)
    app = create_app(
        provider="mock",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
    )

    with TestClient(app) as ready_client:
        response = ready_client.get("/api/ready")

    assert response.status_code == 503
    assert "ffmpeg executable not found" in response.json()["detail"]


def test_ready_reports_non_writable_work_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(
        app_module,
        "_verify_writable_directory",
        lambda path: (_ for _ in ()).throw(OSError("required work directory is not writable")),
    )
    app = create_app(
        provider="mock",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
    )

    with TestClient(app) as ready_client:
        response = ready_client.get("/api/ready")

    assert response.status_code == 503
    assert "required work directory is not writable" in response.json()["detail"]


def test_upload_ping_returns_204_without_creating_jobs_or_probing(monkeypatch, tmp_path, caplog):
    created = []
    original_create = JobManager.create

    def tracking_create(self, *args, **kwargs):
        job = original_create(self, *args, **kwargs)
        created.append(job.id)
        return job

    def forbidden_probe(*args, **kwargs):
        raise AssertionError("upload-ping must not call ffprobe")

    monkeypatch.setattr(JobManager, "create", tracking_create)
    monkeypatch.setattr(app_module, "probe_video", forbidden_probe)
    caplog.set_level("INFO", logger="prometheus.api")
    upload_dir = tmp_path / "uploads"
    app = create_app(
        provider="mock",
        output_dir=tmp_path / "out",
        upload_dir=upload_dir,
    )

    response = TestClient(app).post(
        "/api/upload-ping?upload_ping_id=ping-abc-123",
        headers={"Origin": "https://prometheus-beta-liard.vercel.app"},
        files={"file": ("ping.bin", b"prometheus-upload-ping", "application/octet-stream")},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert created == []
    leftover = [path for path in upload_dir.iterdir() if path.is_file()]
    assert leftover == []
    messages = [record.getMessage() for record in caplog.records]
    assert any("upload_ping=ping-abc-123" in message and "lifecycle=received" in message for message in messages)
    assert any("upload_ping=ping-abc-123" in message and "lifecycle=response status=204" in message for message in messages)
    assert all("upload_attempt=" not in message for message in messages)


def test_upload_ping_without_file_still_returns_204(client):
    response = client.post("/api/upload-ping")
    assert response.status_code == 204
    assert response.content == b""


def test_inspection_upload_logs_safe_attempt_lifecycle(client, caplog):
    caplog.set_level("INFO", logger="prometheus.api")

    response = client.post(
        "/api/inspect?upload_attempt_id=upload-abc-123",
        headers={"Origin": "https://example.test"},
    )

    assert response.status_code == 422
    messages = [record.getMessage() for record in caplog.records]
    assert any("upload_attempt=upload-abc-123" in message and "lifecycle=received" in message for message in messages)
    assert any("upload_attempt=upload-abc-123" in message and "lifecycle=response status=422" in message for message in messages)


def test_api_rejects_non_testnet_payment_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMETHEUS_NIMIQ_NETWORK", "mainnet")

    with pytest.raises(RuntimeError, match="restricted to Nimiq testnet"):
        create_app(
            provider="mock",
            output_dir=tmp_path / "out",
            upload_dir=tmp_path / "uploads",
        )


def test_payment_is_disabled_without_real_ai_provider(client):
    config = client.get("/api/payments/config")
    assert config.status_code == 200
    assert config.json()["enabled"] is False
    assert config.json()["amount_luna"] == 1_000_000
    assert client.post("/api/payments/quotes").status_code == 503


def test_advanced_analysis_requires_verified_payment(tmp_path, synthetic_video):
    app = create_app(
        provider="mock",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
        require_payment=True,
    )
    gated = TestClient(app)
    basic = gated.post("/api/inspect", files={"file": ("video.mp4", synthetic_video.read_bytes(), "video/mp4")})
    basic_id = basic.json()["job_id"]
    _wait_complete(gated, basic_id)
    response = gated.post("/api/analyze", data={"source_job_id": basic_id})
    assert response.status_code == 402
    assert "verified, unused payment" in response.json()["detail"]
    assert gated.post("/api/analyze", files={"file": ("video.mp4", synthetic_video.read_bytes(), "video/mp4")}).status_code == 400


def test_full_analyze_flow(client, synthetic_video):
    response = _upload(client, synthetic_video)
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    _wait_complete(client, job_id)

    result_response = client.get(f"/api/jobs/{job_id}/result")
    assert result_response.status_code == 200
    dto = result_response.json()
    assert dto["job_id"] == job_id
    assert dto["analyzer"]["mode"] == "mock"
    assert dto["scene_count"] == 1
    assert "Reconstructed Generation Prompt" in dto["prompt_markdown"]
    assert dto["scenes"][0]["prompt_markdown"]
    assert dto["scenes"][0]["frames"]
    assert dto["breakdown"]
    assert dto["parameters"]

    frame_url = dto["scenes"][0]["frames"][0]
    frame_response = client.get(frame_url)
    assert frame_response.status_code == 200
    assert frame_response.content[:2] == b"\xff\xd8"


def test_free_local_inspection_flow(client, synthetic_video):
    response = client.post(
        "/api/inspect",
        files={"file": ("video.mp4", synthetic_video.read_bytes(), "video/mp4")},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    _wait_complete(client, job_id)

    result = client.get(f"/api/jobs/{job_id}/result")
    assert result.status_code == 200
    body = result.json()
    assert body["tier"] == "basic"
    assert body["analyzer"]["mode"] == "local"
    assert body["scenes"]
    assert body["prompt_markdown"] == ""
    assert body["breakdown"] == []
    assert client.post(f"/api/jobs/{job_id}/remix", json={"subject": "x"}).status_code == 403

    frame_url = body["scenes"][0]["frames"][0]
    frame_response = client.get(frame_url)
    assert frame_response.status_code == 200
    assert frame_response.content[:2] == b"\xff\xd8"


def test_upload_rejects_non_video(client):
    response = client.post(
        "/api/analyze", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 400


def test_upload_rejects_empty_file(client):
    response = client.post(
        "/api/analyze", files={"file": ("video.mp4", b"", "video/mp4")}
    )
    assert response.status_code == 400


def test_upload_rejects_renamed_invalid_video_before_payment(tmp_path):
    app = create_app(
        provider="mock",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
        require_payment=True,
    )
    gated = TestClient(app)
    response = gated.post(
        "/api/inspect",
        files={"file": ("fake.mp4", b"not a video", "video/mp4")},
    )
    assert response.status_code == 422
    assert "Invalid video" in response.json()["detail"]


def test_upload_reports_missing_ffprobe_dependency(monkeypatch, tmp_path):
    from prometheus.video import probe

    def missing_tool(name):
        raise VideoToolError(f"{name} executable not found")
    monkeypatch.setattr(probe, "resolve_tool", missing_tool)
    app = create_app(provider="mock", output_dir=tmp_path / "out", upload_dir=tmp_path / "uploads")
    response = TestClient(app).post("/api/inspect", files={"file": ("video.mp4", b"video", "video/mp4")})
    assert response.status_code == 503
    assert "ffprobe executable not found" in response.json()["detail"]
    assert list((tmp_path / "uploads").iterdir()) == []


def test_missing_basic_video_cannot_create_quote_or_start_paid_job(monkeypatch, tmp_path, synthetic_video):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    service, holder = _payment_service(tmp_path)
    app = create_app(provider="gemini", output_dir=tmp_path / "out", upload_dir=tmp_path / "uploads", require_payment=True, payment_service=service)
    paid = TestClient(app)
    basic_id = paid.post("/api/inspect", files={"file": ("video.mp4", synthetic_video.read_bytes(), "video/mp4")}).json()["job_id"]
    _wait_complete(paid, basic_id)
    quote = _verify_for_job(service, holder, basic_id)
    next((tmp_path / "out" / basic_id).glob("*/source.mp4")).unlink()
    assert paid.post("/api/payments/quotes", json={"source_job_id": basic_id}).status_code == 404
    response = paid.post("/api/analyze", data={"source_job_id": basic_id, "payment_quote_id": quote["id"], "payment_token": quote["token"]})
    assert response.status_code == 404
    assert "video file is missing" in response.json()["detail"]


def test_upload_limit_is_enforced_and_partial_file_removed(tmp_path):
    app = create_app(
        provider="mock",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=4,
    )
    limited = TestClient(app)
    response = limited.post(
        "/api/inspect", files={"file": ("large.mp4", b"12345", "video/mp4")}
    )
    assert response.status_code == 413
    assert list((tmp_path / "uploads").iterdir()) == []


def test_verified_payment_creates_one_idempotent_advanced_job(tmp_path, synthetic_video):
    service, holder = _payment_service(tmp_path)
    app = create_app(
        provider="mock",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
        require_payment=True,
        payment_service=service,
    )
    paid = TestClient(app)
    files = {"file": ("video.mp4", synthetic_video.read_bytes(), "video/mp4")}
    basic_id = paid.post("/api/inspect", files=files).json()["job_id"]
    _wait_complete(paid, basic_id)
    quote = _verify_for_job(service, holder, basic_id)
    form = {"source_job_id": basic_id, "payment_quote_id": quote["id"], "payment_token": quote["token"]}

    first = paid.post("/api/analyze", data=form)
    assert first.status_code == 202
    job_id = first.json()["job_id"]
    second = paid.post("/api/analyze", data=form)
    assert second.status_code == 202
    assert second.json()["job_id"] == job_id
    _wait_complete(paid, job_id)
    assert paid.get(f"/api/jobs/{job_id}/result").json()["tier"] == "advanced"

    wrong = paid.post(
        "/api/analyze",
        data={**form, "payment_token": "wrong"},
    )
    assert wrong.status_code == 402
    other_basic_id = paid.post("/api/inspect", files=files).json()["job_id"]
    _wait_complete(paid, other_basic_id)
    reused = paid.post("/api/analyze", data={**form, "source_job_id": other_basic_id})
    assert reused.status_code == 402


def test_verified_hash_flows_through_http_to_result_and_remix(tmp_path, synthetic_video):
    service, holder = _payment_service(tmp_path)
    app = create_app(provider="mock", output_dir=tmp_path / "out", upload_dir=tmp_path / "uploads", require_payment=True, payment_service=service)
    paid = TestClient(app)
    basic_id = paid.post("/api/inspect", files={"file": ("video.mp4", synthetic_video.read_bytes(), "video/mp4")}).json()["job_id"]
    _wait_complete(paid, basic_id)
    quote = service.create_quote(basic_id)
    holder["quote"] = quote
    verified = paid.post(f"/api/payments/quotes/{quote['id']}/verify", json={"tx_hash": TX_HASH})
    assert verified.status_code == 200
    assert verified.json()["state"] == "verified"
    assert verified.json()["source_job_id"] == basic_id
    form = {"source_job_id": basic_id, "payment_quote_id": quote["id"], "payment_token": quote["token"]}
    advanced = paid.post("/api/analyze", data=form)
    assert advanced.status_code == 202
    advanced_id = advanced.json()["job_id"]
    _wait_complete(paid, advanced_id)
    assert paid.get(f"/api/jobs/{advanced_id}/result").json()["tier"] == "advanced"
    assert paid.post(f"/api/jobs/{advanced_id}/remix", json={"subject": "a dragon"}).status_code == 200
    assert paid.post("/api/analyze", data=form).json()["job_id"] == advanced_id
    second_basic_id = paid.post("/api/inspect", files={"file": ("new.mp4", synthetic_video.read_bytes(), "video/mp4")}).json()["job_id"]
    _wait_complete(paid, second_basic_id)
    assert paid.post("/api/analyze", data={**form, "source_job_id": second_basic_id}).status_code == 402


def test_payment_quote_requires_completed_basic_job(tmp_path, synthetic_video, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    service, holder = _payment_service(tmp_path)
    app = create_app(
        provider="gemini",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
        require_payment=True,
        payment_service=service,
    )
    paid = TestClient(app)
    assert paid.post("/api/payments/quotes", json={"source_job_id": "missing"}).status_code == 400
    basic_id = paid.post("/api/inspect", files={"file": ("video.mp4", synthetic_video.read_bytes(), "video/mp4")}).json()["job_id"]
    _wait_complete(paid, basic_id)
    quote_response = paid.post("/api/payments/quotes", json={"source_job_id": basic_id})
    assert quote_response.status_code == 200
    assert quote_response.json()["source_job_id"] == basic_id


def test_invalid_staged_upload_is_rejected_before_any_payment(tmp_path):
    app = create_app(
        provider="mock",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
        require_payment=True,
    )
    paid = TestClient(app)

    staged = paid.post(
        "/api/uploads", files={"file": ("fake.mp4", b"not a video", "video/mp4")}
    )

    assert staged.status_code == 422


def test_unknown_job_returns_404(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/result").status_code == 404
    assert client.post("/api/jobs/nope/remix", json={"subject": "x"}).status_code == 404


def test_result_before_completion_returns_409(client, synthetic_video):
    response = _upload(client, synthetic_video)
    job_id = response.json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}/result").status_code == 409


def test_web_index_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert '<span class="wordmark">Orb</span>' in response.text


def test_configured_cors_allows_the_deployed_frontend(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMETHEUS_CORS_ORIGINS", "https://prometheus.vercel.app")
    app = create_app(provider="mock", output_dir=tmp_path / "out", upload_dir=tmp_path / "uploads")
    response = TestClient(app).options(
        "/api/health",
        headers={
            "Origin": "https://prometheus.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://prometheus.vercel.app"


def test_result_includes_video_preview_url(client, synthetic_video):
    response = _upload(client, synthetic_video)
    job_id = response.json()["job_id"]
    _wait_complete(client, job_id)
    dto = client.get(f"/api/jobs/{job_id}/result").json()
    assert dto["video"]["preview_url"] == f"/api/jobs/{job_id}/frames/source.mp4"
    preview = client.get(dto["video"]["preview_url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("video/")
    assert len(preview.content) > 1000


def test_remix_rebuilds_prompt_from_existing_analysis(client, synthetic_video):
    response = _upload(client, synthetic_video)
    job_id = response.json()["job_id"]
    _wait_complete(client, job_id)

    remix = client.post(f"/api/jobs/{job_id}/remix", json={"subject": "a chrome dragon"})
    assert remix.status_code == 200
    body = remix.json()
    assert body["applied"] == ["subject"]
    assert "a chrome dragon" in body["prompt_markdown"]
    assert "Reconstructed Generation Prompt" in body["prompt_markdown"]


def test_remix_rejects_unknown_attributes(client, synthetic_video):
    response = _upload(client, synthetic_video)
    job_id = response.json()["job_id"]
    _wait_complete(client, job_id)
    remix = client.post(f"/api/jobs/{job_id}/remix", json={"soundtrack": "synthwave"})
    assert remix.status_code == 400


def test_remix_rejects_empty_overrides(client, synthetic_video):
    response = _upload(client, synthetic_video)
    job_id = response.json()["job_id"]
    _wait_complete(client, job_id)
    remix = client.post(f"/api/jobs/{job_id}/remix", json={"subject": "   "})
    assert remix.status_code == 400


def test_gemini_without_key_fails_without_mock(monkeypatch, tmp_path, synthetic_video):
    for name in (
        "GEMINI_API_KEY", "PROMETHEUS_API_KEY", "GOOGLE_API_KEY",
        "OPENAI_API_KEY", "PROMETHEUS_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    app = create_app(
        provider="gemini",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
        require_payment=False,
    )
    keyless = TestClient(app)
    response = keyless.post(
        "/api/analyze",
        files={"file": ("video.mp4", synthetic_video.read_bytes(), "video/mp4")},
    )
    assert response.status_code == 503
    assert "server-side API key" in response.json()["detail"]


def test_ai_failure_retries_same_paid_job(monkeypatch, tmp_path, synthetic_video):
    for name in ("GEMINI_API_KEY", "PROMETHEUS_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    service, holder = _payment_service(tmp_path)
    app = create_app(
        provider="gemini",
        output_dir=tmp_path / "out",
        upload_dir=tmp_path / "uploads",
        require_payment=True,
        payment_service=service,
    )
    paid = TestClient(app)
    files = {"file": ("video.mp4", synthetic_video.read_bytes(), "video/mp4")}
    basic_id = paid.post("/api/inspect", files=files).json()["job_id"]
    _wait_complete(paid, basic_id)
    quote = _verify_for_job(service, holder, basic_id)
    form = {"source_job_id": basic_id, "payment_quote_id": quote["id"], "payment_token": quote["token"]}

    first = paid.post("/api/analyze", data=form)
    assert first.status_code == 202
    first_job_id = first.json()["job_id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        job = paid.get(f"/api/jobs/{first_job_id}").json()
        if job["state"] == "error":
            break
        time.sleep(0.1)
    assert job["state"] == "error"

    retry = paid.post("/api/analyze", data=form)
    assert retry.status_code == 202
    assert retry.json()["job_id"] == first_job_id
