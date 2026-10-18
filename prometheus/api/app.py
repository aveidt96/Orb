from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from prometheus import __version__
from prometheus.analysis.prompt_builder import build_reconstructed_prompt
from prometheus.analysis.opencv_telemetry import analyze_image_cv
from prometheus.analysis.orb_ai import OrbAIService, _visual_from_report, video_generation_prompt
from prometheus.analysis.remix import apply_remix
from prometheus.analysis.schema import AnalysisReport
from prometheus.api.dto import build_basic_result_dto, build_result_dto
from prometheus.api.jobs import Job, JobManager
from prometheus.api.orb_credits import CHAIN_ID, CreditConfig, CreditError, CreditService
from prometheus.api.orb_deployment import validate_public_deployment
from prometheus.api.orb_usdg import USDG_PRICE, parse_usdg_price
from prometheus.api.payments import PaymentConfig, PaymentError, PaymentPending, PaymentService
from prometheus.config import PrometheusConfig
from prometheus.errors import PrometheusError
from prometheus.pipeline import PrometheusPipeline
from prometheus.performance import TimingMiddleware, current, metric, observe, stage, timed
from prometheus.storage import prepare_run_directory, prepare_scene_directory
from prometheus.video.probe import ValidatedVideo, probe_video, video_identity
from prometheus.video.sampler import FrameSampler
from prometheus.video.segmenter import SceneSegmenter
from prometheus.video.tools import VideoToolError, resolve_tool

_ROOT_DIR = Path(__file__).resolve().parents[2]
_WEB_DIR = _ROOT_DIR / "web"
_BUILT_WEB_DIR = _ROOT_DIR / "web_dist"
_ALLOWED_EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm")
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_SCENE_STAGE_RE = re.compile(r"Analyzing scene (\d+) of (\d+)")
_DEFAULT_NIMIQ_RECIPIENT = "NQ43 HJUE 9G1D 5LQF C752 5T7H EJ9M 4QEM 1CB1"
_DEFAULT_NIMIQ_RPC_URL = "https://rpc.testnet.nimiqwatch.com/"
_DEFAULT_NIMIQ_AMOUNT_LUNA = 1_000_000
_STAGED_UPLOAD_LIFETIME_SECONDS = 60 * 60
_UPLOAD_ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_UPLOAD_PING_MAX_BYTES = 64 * 1024
_LOG = logging.getLogger("prometheus.api")


_DEFAULT_LOCAL_TREASURY = "0xc855D21175D81C852E657169424FA974171394F1"
_DEFAULT_ARBITRUM_SEPOLIA_RPC = "https://sepolia-rollup.arbitrum.io/rpc"
_DOTENV_LOADED = False


def _load_local_dotenv_defaults() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED or "PYTEST_CURRENT_TEST" in os.environ:
        return
    _DOTENV_LOADED = True
    env_file = _ROOT_DIR / ".env"
    safe_keys = {
        "GEMINI_API_KEY",
        "PROMETHEUS_API_KEY",
        "GOOGLE_API_KEY",
        "ORB_JUDGE_DEMO_CODE",
        "ORB_JUDGE_DAILY_CAP",
        "ORB_JUDGE_IP_DAILY_LIMIT",
        "ORB_CREDITS_ENABLED",
        "ORB_ARBITRUM_RPC_URL",
        "ORB_CREDIT_RECEIVER",
        "ORB_TREASURY_ADDRESS",
        "ORB_CREDIT_PRICE_WEI",
        "ORB_PAYMENT_CONFIRMATIONS",
        "ORB_COMPUTE_ENV",
        "ORB_AWS_S3_BUCKET",
        "AWS_S3_BUCKET",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    }
    if env_file.is_file():
        try:
            for raw_line in env_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key in safe_keys and val and not os.environ.get(key):
                    os.environ[key] = val
        except OSError:
            pass
    if os.environ.get("ORB_ENV", "local") == "local":
        os.environ.setdefault("ORB_ENV", "local")
        os.environ.setdefault("ORB_CREDITS_ENABLED", "1")
        os.environ.setdefault("ORB_PUBLIC_ORIGIN", "http://127.0.0.1:8000")
        os.environ.setdefault("ORB_ARBITRUM_RPC_URL", _DEFAULT_ARBITRUM_SEPOLIA_RPC)
        treasury = (
            os.environ.get("ORB_TREASURY_ADDRESS")
            or os.environ.get("ORB_CREDIT_RECEIVER")
            or _DEFAULT_LOCAL_TREASURY
        ).strip()
        os.environ.setdefault("ORB_TREASURY_ADDRESS", treasury)
        os.environ.setdefault("ORB_CREDIT_RECEIVER", treasury)
        os.environ.setdefault("ORB_JUDGE_IP_DAILY_LIMIT", "50")


def _resolve_provider() -> str:
    _load_local_dotenv_defaults()
    env = os.environ.get("PROMETHEUS_PROVIDER")
    if env:
        return env
    if (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("PROMETHEUS_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    ):
        return "gemini"
    return "mock"


def _provider_is_ready(provider: str) -> bool:
    env_names = {
        "gemini": ("PROMETHEUS_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "openai": ("PROMETHEUS_OPENAI_API_KEY", "OPENAI_API_KEY"),
    }
    return any(os.environ.get(name) for name in env_names.get(provider, ()))


def _storage_path(value: Path | str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else _ROOT_DIR / path).resolve()


def _cors_origins(value: str | None) -> list[str]:
    return [origin.strip().rstrip("/") for origin in (value or "").split(",") if origin.strip()]


def _verify_writable_directory(path: Path) -> None:
    """Prove the local work directory can be used, without retaining data."""
    if not path.is_dir():
        raise OSError("required work directory is unavailable")
    probe = path / f".prometheus-ready-{uuid.uuid4().hex}"
    try:
        with probe.open("xb"):
            pass
    except OSError as exc:
        raise OSError("required work directory is not writable") from exc
    finally:
        probe.unlink(missing_ok=True)


_VERIFIED_VIDEO_TOOLS: set[str] = set()


def _verify_video_tool(name: str) -> None:
    if name in _VERIFIED_VIDEO_TOOLS:
        return
    try:
        executable = resolve_tool(name)
        subprocess.run(
            [executable, "-version"],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        _VERIFIED_VIDEO_TOOLS.add(name)
    except (VideoToolError, OSError, subprocess.SubprocessError) as exc:
        try:
            import cv2  # noqa: F401
            _VERIFIED_VIDEO_TOOLS.add(name)
            return
        except ImportError:
            if isinstance(exc, VideoToolError):
                raise
            raise VideoToolError(f"{name} executable is unavailable") from exc


def _safe_upload_attempt_id(value: str | None) -> str:
    if value and _UPLOAD_ATTEMPT_ID_RE.fullmatch(value):
        return value
    return "missing" if not value else "invalid"


def _safe_origin(value: str | None) -> str:
    if not value:
        return "missing"
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "invalid"


def _log_upload_lifecycle(attempt_id: str, origin: str, lifecycle: str, status: int | None = None) -> None:
    fields = (
        f"upload_attempt={attempt_id} timestamp={datetime.now(timezone.utc).isoformat()} "
        f"reached_fastapi=true origin={origin} lifecycle={lifecycle}"
    )
    if status is not None:
        fields = f"{fields} status={status}"
    _LOG.info(fields)


def _log_upload_ping_lifecycle(ping_id: str, origin: str, lifecycle: str, status: int | None = None) -> None:
    fields = (
        f"upload_ping={ping_id} timestamp={datetime.now(timezone.utc).isoformat()} "
        f"reached_fastapi=true origin={origin} lifecycle={lifecycle}"
    )
    if status is not None:
        fields = f"{fields} status={status}"
    _LOG.info(fields)


def create_app(
    provider: str | None = None,
    model: str | None = None,
    output_dir: Path | str | None = None,
    upload_dir: Path | str | None = None,
    max_upload_bytes: int = 200 * 1024 * 1024,
    require_payment: bool | None = None,
    payment_service: PaymentService | None = None,
    orb_ai_service: OrbAIService | None = None,
    orb_credit_service: CreditService | None = None,
) -> FastAPI:
    _load_local_dotenv_defaults()
    provider = provider or os.environ.get("ORB_AI_PROVIDER") or _resolve_provider()
    model = model or os.environ.get("ORB_AI_MODEL")
    public_mode = os.environ.get("ORB_ENV") == "production"
    output_default = "/tmp/orb_output" if public_mode else "api_output"
    upload_default = "/tmp/orb_uploads" if public_mode else "uploads"
    output_root = _storage_path(output_dir or os.environ.get("ORB_OUTPUT_DIR")
                                or (output_default if public_mode else os.environ.get("PROMETHEUS_API_OUTPUT_DIR", output_default)))
    upload_root = _storage_path(upload_dir or os.environ.get("ORB_UPLOAD_DIR")
                                or (upload_default if public_mode else os.environ.get("PROMETHEUS_API_UPLOAD_DIR", upload_default)))
    database_url = os.environ.get("ORB_DATABASE_URL", "")
    payment_method = os.environ.get("ORB_PAYMENT_METHOD", "native")
    payment_methods_value = os.environ.get("ORB_PAYMENT_METHODS")
    payment_methods = tuple(part.strip() for part in payment_methods_value.split(",")) if payment_methods_value is not None else ()
    credit_db = _storage_path(os.environ.get("ORB_CREDIT_DB", str(output_root / (
        "orb_usdg_credits.sqlite3" if payment_method == "usdg" else "orb_credits.sqlite3"))))
    validate_public_deployment(upload_root, database_url)
    output_root.mkdir(parents=True, exist_ok=True)
    upload_root.mkdir(parents=True, exist_ok=True)
    receiver_addr = (
        os.environ.get("ORB_CREDIT_RECEIVER")
        or os.environ.get("ORB_TREASURY_ADDRESS")
        or ""
    ).strip()
    credit_service = orb_credit_service or CreditService(CreditConfig(
        database=credit_db,
        database_url=database_url if public_mode else "",
        public_origin=os.environ.get("ORB_PUBLIC_ORIGIN", "").rstrip("/"),
        rpc_url=os.environ.get("ORB_ARBITRUM_RPC_URL", ""),
        receiver=receiver_addr,
        price_wei=int(os.environ.get("ORB_CREDIT_PRICE_WEI", "1000000000000")),
        confirmations=int(os.environ.get("ORB_PAYMENT_CONFIRMATIONS", "3")),
        enabled=os.environ.get("ORB_CREDITS_ENABLED") == "1",
        payment_method=payment_method,
        payment_methods=payment_methods,
        chain_id=int(os.environ.get("ORB_CHAIN_ID", "421614")),
        usdg_contract=os.environ.get("ORB_USDG_CONTRACT_ADDRESS", "0xFFC95faa3d63Cde504a05B567C600B78C0b41892"),
        usdg_decimals=int(os.environ.get("ORB_USDG_DECIMALS", "6")),
        usdg_price=parse_usdg_price(os.environ.get("ORB_CREDIT_PRICE_USDG_BASE_UNITS", str(USDG_PRICE))),
        deployment_target=os.environ.get("ORB_DEPLOYMENT_TARGET", ""),
        judge_demo_code=os.environ.get("ORB_JUDGE_DEMO_CODE", "").strip(),
        judge_daily_cap=int(os.environ.get("ORB_JUDGE_DAILY_CAP", "150")),
        judge_ip_daily_limit=int(os.environ.get("ORB_JUDGE_IP_DAILY_LIMIT", "3")),
    ))
    if public_mode and (not credit_service.database.postgres
                        or credit_service.config.database_url != database_url):
        raise RuntimeError("Production requires the configured Orb Postgres credit and result store.")
    credit_service.reconcile(output_root)
    # Orb isolation: the inherited Nimiq payment code stays dormant unless it
    # is explicitly enabled for development. Orb will use a separate
    # Arbitrum-based payment system in a later stage; nothing may depend on
    # the original Prometheus payment accounts or testnet infrastructure.
    payments_enabled = (
        os.environ.get("ORB_ENV") == "local"
        and os.environ.get("ORB_ENABLE_NIMIQ_PAYMENTS", "").strip() == "1"
    )
    if require_payment is None:
        require_payment = provider != "mock" and payments_enabled
    payment_network = os.environ.get("PROMETHEUS_NIMIQ_NETWORK", "testnet")
    if payments_enabled and payment_network != "testnet":
        raise RuntimeError("Prometheus Mini App development is restricted to Nimiq testnet.")
    payment_service = payment_service or (
        PaymentService(
            PaymentConfig(
                recipient=os.environ.get("PROMETHEUS_NIMIQ_RECIPIENT", _DEFAULT_NIMIQ_RECIPIENT),
                amount_luna=int(os.environ.get("PROMETHEUS_NIMIQ_AMOUNT_LUNA", _DEFAULT_NIMIQ_AMOUNT_LUNA)),
                rpc_url=os.environ.get("PROMETHEUS_NIMIQ_RPC_URL", _DEFAULT_NIMIQ_RPC_URL),
                network=payment_network,
                confirmations=int(os.environ.get("PROMETHEUS_NIMIQ_CONFIRMATIONS", "1")),
            ),
            database=os.environ.get("PROMETHEUS_PAYMENT_DB", str(output_root / "payments.db")),
        )
        if payments_enabled
        else None
    )

    app = FastAPI(title="Orb", version=__version__, docs_url="/api/docs")
    app.add_middleware(TimingMiddleware)
    app.state.prometheus_startup_complete = False
    orb_origin = os.environ.get("ORB_PUBLIC_ORIGIN", "").rstrip("/")
    cors_origins = [orb_origin] if orb_origin else []
    if os.environ.get("ORB_ENV") == "local":
        cors_origins.extend(origin for origin in _cors_origins(os.environ.get("PROMETHEUS_CORS_ORIGINS"))
                            if origin not in cors_origins)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-Orb-Idempotency-Key"],
        )
    manager = JobManager(max_workers=1)
    staged_uploads: dict[str, tuple[str, Path, float]] = {}
    staged_uploads_lock = threading.Lock()

    def _client_ip(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        return request.client.host if request.client and request.client.host else "unknown"

    def _local_ai_allowed(request: Request) -> bool:
        return (
            os.environ.get("ORB_ENV") == "local"
            and os.environ.get("ORB_AI_LOCAL_TESTING") == "1"
            and request.client is not None
            and request.client.host in {"127.0.0.1", "::1", "testclient"}
            and (request.url.hostname or "") in {"localhost", "127.0.0.1", "::1", "testserver"}
            and not request.headers.get("x-forwarded-for")
            and not request.headers.get("forwarded")
        )

    @timed("authorization")
    def _authorize_ai(request: Request) -> str | None:
        """Return a paid wallet or None for explicit loopback-only testing."""
        if provider == "mock" or not _provider_is_ready(provider):
            raise HTTPException(status_code=503, detail="Configure a real Orb AI provider and server-side API key.")
        auth_header = request.headers.get("authorization")
        if _local_ai_allowed(request) and not (
            auth_header and (credit_service.config.ready or credit_service.config.judge_ready)
        ):
            return None
        if not (credit_service.config.ready or credit_service.config.judge_ready):
            raise HTTPException(status_code=402, detail="AI operations require verified testnet credits. Payments are not configured.")
        try:
            if credit_service.config.public_origin:
                credit_service._check_origin(request.headers.get("origin"))
            return credit_service.authenticate(auth_header)
        except CreditError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    def _wallet(request: Request, *, mutating: bool = False) -> str:
        try:
            if mutating and credit_service.config.public_origin:
                credit_service._check_origin(request.headers.get("origin"))
            return credit_service.authenticate(request.headers.get("authorization"))
        except CreditError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    def _paid_job_owner(request: Request, job_id: str):
        paid = credit_service.paid_job(job_id)
        if paid is not None and _wallet(request) != paid["wallet"]:
            raise HTTPException(status_code=404, detail="Unknown job.")
        return paid

    def _recover_paid_result(job_id: str, paid):
        if paid is None:
            return None, None
        saved = credit_service.result(job_id, output_root)
        if (paid["status"] == "reserved" and isinstance(saved, dict)
                and saved.get("job_id") == job_id
                and isinstance(saved.get("prompt"), str) and saved["prompt"].strip()):
            with stage("credit_settlement"):
                credit_service.settle(job_id, True)
            paid = credit_service.paid_job(job_id)
        return saved, paid

    def _orb_service() -> OrbAIService:
        return orb_ai_service or OrbAIService(provider, _make_config("ai").analyzer.resolved_model())

    @app.on_event("startup")
    async def mark_startup_complete() -> None:
        app.state.prometheus_startup_complete = True

    @app.middleware("http")
    async def log_inspection_upload(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/api/upload-ping":
            ping_id = _safe_upload_attempt_id(request.query_params.get("upload_ping_id"))
            origin = _safe_origin(request.headers.get("origin"))
            _log_upload_ping_lifecycle(ping_id, origin, "received")
            try:
                response = await call_next(request)
            except BaseException:
                _log_upload_ping_lifecycle(ping_id, origin, "interrupted")
                raise
            _log_upload_ping_lifecycle(ping_id, origin, "response", response.status_code)
            return response

        if request.method != "POST" or request.url.path != "/api/inspect":
            return await call_next(request)

        attempt_id = _safe_upload_attempt_id(request.query_params.get("upload_attempt_id"))
        origin = _safe_origin(request.headers.get("origin"))
        _log_upload_lifecycle(attempt_id, origin, "received")
        try:
            response = await call_next(request)
        except BaseException:
            _log_upload_lifecycle(attempt_id, origin, "interrupted")
            raise
        _log_upload_lifecycle(attempt_id, origin, "response", response.status_code)
        return response

    def _cleanup_staged_uploads() -> None:
        cutoff = time.time() - _STAGED_UPLOAD_LIFETIME_SECONDS
        with staged_uploads_lock:
            expired = [
                staged_uploads.pop(upload_id)
                for upload_id, upload in list(staged_uploads.items())
                if upload[2] < cutoff
            ]
        for _, path, _ in expired:
            path.unlink(missing_ok=True)

    def _take_staged_upload(upload_id: str) -> tuple[str, Path] | None:
        _cleanup_staged_uploads()
        with staged_uploads_lock:
            upload = staged_uploads.pop(upload_id, None)
        if upload is None:
            return None
        return upload[0], upload[1]

    def _make_config(job_id: str) -> PrometheusConfig:
        config = PrometheusConfig()
        config.analyzer.provider = provider
        config.analyzer.model = model or ("gemini-3.8-flash" if provider == "gemini" else None)
        config.output.directory = output_root / job_id
        return config

    @timed("file_hash")
    def _fingerprint_file(path: Path, operation: str) -> str:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return hashlib.sha256(f"{operation}:{digest}".encode()).hexdigest()

    @timed("credit_reservation")
    def _reserve_paid(wallet: str | None, request: Request, operation: str,
                      fingerprint: str, job: Job) -> tuple[str, bool]:
        if wallet is None:
            return job.id, True
        try:
            return credit_service.reserve(wallet, operation,
                                          request.headers.get("x-orb-idempotency-key", ""),
                                          fingerprint, job.id)
        except CreditError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    def _run_job(job: Job, video_path: Path) -> None:
        def _progress(stage: str) -> None:
            fields: dict[str, Any] = {"stage": stage}
            match = _SCENE_STAGE_RE.match(stage)
            if match:
                fields["stage"] = f"Analyzing scenes ({match.group(1)}/{match.group(2)})"
            manager.update(job.id, **fields)

        try:
            config = _make_config(job.id)
            pipeline = PrometheusPipeline(config=config)
            result = pipeline.run(video_path, progress=_progress)
            shutil.copyfile(video_path, result.output.run_dir / job.source_file)
            if require_payment:
                payment_service.finalize(job.id)
            manager.update(job.id, run_dir=result.output.run_dir, state="complete", stage="Complete")
        except Exception:
            shutil.rmtree(output_root / job.id, ignore_errors=True)
            raise
        finally:
            video_path.unlink(missing_ok=True)

    def _run_basic_job(job: Job, video_path: Path) -> None:
        try:
            config = _make_config(job.id)
            manager.update(job.id, stage="Inspecting video")
            metadata = probe_video(video_path)
            run_dir, _ = prepare_run_directory(video_path, config.output.directory)
            manager.update(job.id, stage="Detecting scene cuts")
            scenes = SceneSegmenter(config.segmentation).segment(metadata)
            sampler = FrameSampler(config.sampling)
            scene_data = []
            for scene in scenes:
                scene_dir = prepare_scene_directory(run_dir, scene)
                frames = sampler.sample_range(
                    metadata, scene.start, scene.end, 1, scene_dir / "frames"
                )
                scene_data.append({**scene.to_dict(), "frames": [frame.to_dict() for frame in frames]})
            (run_dir / "basic.json").write_text(
                json.dumps({"video": metadata.to_dict(), "scenes": scene_data}, indent=2),
                encoding="utf-8",
            )
            shutil.copyfile(video_path, run_dir / job.source_file)
            manager.update(job.id, run_dir=run_dir, state="complete", stage="Complete")
        except Exception:
            shutil.rmtree(output_root / job.id, ignore_errors=True)
            raise
        finally:
            video_path.unlink(missing_ok=True)

    @timed("upload_save")
    async def _save_upload(file: UploadFile, allow_images: bool = False) -> tuple[str, Path]:
        filename = file.filename or ""
        allowed = _ALLOWED_EXTENSIONS + (_IMAGE_EXTENSIONS if allow_images else ())
        if Path(filename).suffix.lower() not in allowed:
            raise HTTPException(status_code=400, detail="Unsupported file type. Use JPEG, PNG, WebP, MP4, MOV, M4V, or WebM.")
        suffix = Path(filename).suffix.lower()
        limit = _MAX_IMAGE_BYTES if suffix in _IMAGE_EXTENSIONS else max_upload_bytes
        destination = upload_root / f"{uuid.uuid4().hex}{suffix}"
        size = 0
        try:
            with destination.open("wb") as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        limit_mb = limit / 1024 / 1024
                        raise HTTPException(
                            status_code=413,
                            detail=f"File exceeds the {limit_mb:g} MB limit.",
                        )
                    out.write(chunk)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        if size == 0:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        metric("input_bytes", size)
        return filename, destination

    async def _validate_upload(destination: Path) -> ValidatedVideo | None:
        try:
            identity = video_identity(destination)
            metadata = await run_in_threadpool(probe_video, destination)
            return ValidatedVideo(metadata, identity) if identity == video_identity(destination) else None
        except VideoToolError as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=503, detail=f"Video validation is unavailable: {exc}")
        except PrometheusError as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=f"Invalid video: {exc}")
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=503, detail=f"Video validation is unavailable: {exc}")

    @timed("file_validation")
    async def _validate_orb_media(destination: Path) -> dict[str, Any]:
        if destination.suffix.lower() not in _IMAGE_EXTENSIONS:
            validated = await _validate_upload(destination)
            return {"kind": "video", "validated_video": validated}
        try:
            from PIL import Image, UnidentifiedImageError

            with Image.open(destination) as image:
                width, height = image.size
                expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}[destination.suffix.lower()]
                if image.format != expected or width < 1 or height < 1 or width * height > 32_000_000:
                    raise ValueError("Image type or dimensions are invalid.")
                image.verify()
            metric("width", width)
            metric("height", height)
            return {"kind": "image", "width": width, "height": height}
        except (UnidentifiedImageError, Image.DecompressionBombError, ValueError, OSError) as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="Invalid image file or dimensions.") from exc

    @app.get("/api/health")
    def health() -> dict:
        analyzer_config = _make_config("health").analyzer
        return {
            "status": "ok",
            "version": __version__,
            "analyzer": {
                "provider": provider,
                "model": analyzer_config.resolved_model(),
            },
            "payment_required": require_payment,
            "orb_ai_access": (
                "local" if provider != "mock" and _provider_is_ready(provider)
                and os.environ.get("ORB_ENV") == "local"
                and os.environ.get("ORB_AI_LOCAL_TESTING") == "1"
                else "configuration_required" if provider == "mock" or not _provider_is_ready(provider)
                else "credits" if (credit_service.config.ready or credit_service.config.judge_ready)
                else "credits_unavailable"
            ),
        }

    @app.get("/api/orb/credits/config")
    def orb_credit_config() -> dict:
        from eth_utils import is_address, to_checksum_address

        treasury = (
            to_checksum_address(credit_service.config.receiver)
            if is_address(credit_service.config.receiver)
            else ""
        )
        result = {"enabled": credit_service.config.ready and provider != "mock" and _provider_is_ready(provider),
                "chain_id": CHAIN_ID,
                "network": "Arbitrum Sepolia", "testnet_only": True,
                "treasury_address": treasury,
                "price_wei": str(credit_service.config.price_wei),
                "credit_options": [1, 3, 5], "confirmations": credit_service.config.confirmations,
                "judge_demo_enabled": credit_service.config.judge_ready}
        methods = {"native_eth": {"enabled": "native_eth" in credit_service.config.methods,
                                  "symbol": "ETH", "decimals": 18, "price_wei": str(credit_service.config.price_wei)},
                   "usdg": {"enabled": "usdg" in credit_service.config.methods}}
        if "usdg" in credit_service.config.methods:
            from prometheus.api.orb_usdg import usdg_payment_config
            methods["usdg"].update(usdg_payment_config(credit_service.config))
        result.update(payment_methods=methods, deployment_target=credit_service.config.deployment_target)
        # Compatibility for already-deployed single-method clients.
        if credit_service.config.methods == ("usdg",):
            result.update(methods["usdg"])
            result["enabled"] = credit_service.config.ready and provider != "mock" and _provider_is_ready(provider)
            result.pop("price_wei")
        return result

    @app.post("/api/orb/judge-session")
    def orb_judge_session(request: Request, payload: dict) -> dict:
        try:
            return credit_service.create_judge_session(
                payload.get("code", "") if isinstance(payload, dict) else "",
                _client_ip(request),
                request.headers.get("origin"),
            )
        except CreditError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    @app.post("/api/orb/wallet/challenge")
    def orb_wallet_challenge(request: Request, payload: dict) -> dict:
        try:
            return credit_service.challenge(payload.get("address", ""), request.headers.get("origin"))
        except CreditError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    @app.post("/api/orb/wallet/sign-in")
    def orb_wallet_sign_in(request: Request, payload: dict) -> dict:
        try:
            return credit_service.sign_in(payload.get("nonce", ""), payload.get("signature", ""),
                                          request.headers.get("origin"))
        except CreditError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    @app.post("/api/orb/wallet/logout")
    def orb_wallet_logout(request: Request) -> dict:
        try:
            if credit_service.config.public_origin or request.headers.get("origin") is not None:
                credit_service._check_origin(request.headers.get("origin"))
            credit_service.logout(request.headers.get("authorization"))
        except CreditError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        return {"status": "signed_out"}

    @app.get("/api/orb/credits/balance")
    def orb_credit_balance(request: Request) -> dict:
        return credit_service.balance(_wallet(request))

    @app.post("/api/orb/credits/quotes")
    def orb_credit_quote(request: Request, payload: dict) -> dict:
        wallet = _wallet(request, mutating=True)
        if provider == "mock" or not _provider_is_ready(provider):
            raise HTTPException(status_code=503, detail="Orb AI is not configured for testnet credits.")
        try:
            return credit_service.create_quote(wallet, payload.get("credits"), payload.get("payment_method"))
        except CreditError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    @app.post("/api/orb/credits/quotes/{quote_id}/verify")
    def orb_credit_verify(request: Request, quote_id: str, payload: dict) -> dict:
        wallet = _wallet(request, mutating=True)
        try:
            return credit_service.verify_purchase(wallet, quote_id, payload.get("tx_hash", ""))
        except CreditError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    @app.get("/api/ready")
    def ready() -> dict:
        """Check only local prerequisites for accepting a first upload."""
        if not app.state.prometheus_startup_complete:
            raise HTTPException(status_code=503, detail="Service startup is still in progress.")
        try:
            _verify_writable_directory(upload_root)
            _verify_writable_directory(output_root)
            _verify_video_tool("ffmpeg")
            _verify_video_tool("ffprobe")
            if manager is None:
                raise RuntimeError("analysis job manager is unavailable")
            config = _make_config("ready")
            if not config.analyzer.provider or not config.output.directory:
                raise RuntimeError("required analysis configuration is unavailable")
        except (OSError, RuntimeError, VideoToolError) as exc:
            raise HTTPException(status_code=503, detail=f"Service is not ready: {exc}") from exc
        return {"status": "ready"}

    @app.post("/api/upload-ping", status_code=204)
    async def upload_ping(file: UploadFile | None = File(default=None)) -> Response:
        """Prove the multipart POST path without creating work or storing media."""
        if file is not None:
            size = 0
            while chunk := await file.read(8192):
                size += len(chunk)
                if size > _UPLOAD_PING_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="Upload ping is limited to 64 KB.")
        return Response(status_code=204)

    @app.get("/api/payments/config")
    def payment_config() -> dict:
        if not payments_enabled or payment_service is None:
            raise HTTPException(status_code=503, detail="Payments are not enabled in this build.")
        config = payment_service.public_config()
        config["enabled"] = bool(require_payment and _provider_is_ready(provider))
        return config

    @app.post("/api/payments/quotes")
    def create_payment_quote(payload: dict | None = None) -> dict:
        if not payments_enabled or not require_payment or not _provider_is_ready(provider):
            raise HTTPException(status_code=503, detail="Advanced AI analysis is not configured.")
        source_job_id = payload.get("source_job_id") if isinstance(payload, dict) else None
        source_job = manager.get(source_job_id) if isinstance(source_job_id, str) else None
        if source_job is None or source_job.tier != "basic" or source_job.state != "complete":
            raise HTTPException(status_code=400, detail="A completed basic analysis is required before payment.")
        if source_job.run_dir is None or not (source_job.run_dir / source_job.source_file).is_file():
            raise HTTPException(status_code=404, detail="Basic analysis video file is missing.")
        return payment_service.create_quote(source_job_id)

    @app.post("/api/payments/quotes/{quote_id}/verify")
    def verify_payment_quote(quote_id: str, payload: dict) -> dict:
        if not payments_enabled or payment_service is None:
            raise HTTPException(status_code=503, detail="Payments are not enabled in this build.")
        tx_hash = payload.get("tx_hash") if isinstance(payload, dict) else None
        if tx_hash is not None and not isinstance(tx_hash, str):
            raise HTTPException(status_code=400, detail="Transaction hash must be a string.")
        try:
            return payment_service.verify(quote_id, tx_hash)
        except PaymentPending as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except PaymentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/uploads", status_code=201)
    async def stage_upload(file: UploadFile = File(...)) -> dict:
        if public_mode:
            raise HTTPException(status_code=404, detail="Unknown operation.")
        filename, destination = await _save_upload(file)
        await _validate_upload(destination)
        _cleanup_staged_uploads()
        upload_id = uuid.uuid4().hex
        with staged_uploads_lock:
            staged_uploads[upload_id] = (filename, destination, time.time())
        return {
            "upload_id": upload_id,
            "name": filename,
            "size": destination.stat().st_size,
        }

    @app.post("/api/inspect", status_code=202)
    async def inspect(file: UploadFile = File(...)) -> dict:
        if public_mode:
            raise HTTPException(status_code=404, detail="Unknown operation.")
        filename, destination = await _save_upload(file)
        await _validate_upload(destination)
        job = manager.create(
            video_name=filename,
            tier="basic",
            source_file=f"source{destination.suffix.lower()}",
        )
        manager.submit(job.id, lambda: _run_basic_job(job, destination))
        return {"job_id": job.id}

    def _run_orb_visual_job(job: Job, source: Path, media: dict[str, Any], operation: str,
                            wallet: str | None = None) -> None:
        result_saved = False
        try:
            manager.update(job.id, stage="Analyzing visual reference")
            if media["kind"] == "video":
                config = _make_config(job.id)
                pipeline = PrometheusPipeline(config=config)
                result = pipeline.run(source, progress=lambda stage: manager.update(job.id, stage=stage),
                                      validated_video=media["validated_video"])
                run_dir = result.output.run_dir
                analysis = result.report.to_dict()
                cv_telemetry = result.opencv_telemetry
                if operation == "decode":
                    payload = {"prompt": video_generation_prompt(result.prompt), "visual_analysis": _visual_from_report(analysis),
                               "refinements": []}
                else:
                    manager.update(job.id, stage="Composing prompt")
                    service = _orb_service()
                    try:
                        payload = service.compose_video(analysis, cv_telemetry=cv_telemetry)
                    except TypeError:
                        payload = service.compose_video(analysis)
                if cv_telemetry is not None:
                    payload["opencv_telemetry"] = cv_telemetry
                video_result = build_result_dto(job.id, run_dir, job.video_name, job.source_file)
                payload["video"] = video_result["video"]
                payload["scenes"] = video_result["scenes"]
            else:
                manager.update(job.id, stage="Analyzing image")
                run_dir = output_root / job.id
                run_dir.mkdir(parents=True, exist_ok=True)
                service = _orb_service()
                try:
                    payload = service.image(operation, source, run_dir=run_dir)
                except TypeError:
                    payload = service.image(operation, source)
                if "opencv_telemetry" not in payload:
                    try:
                        payload["opencv_telemetry"] = analyze_image_cv(source, output_dir=run_dir).to_dict()
                    except Exception:
                        pass
                payload["image"] = {
                    "name": job.video_name, "width": media["width"], "height": media["height"],
                    "preview_url": f"/api/jobs/{job.id}/frames/{job.source_file}",
                }
            cv_meta = payload.get("opencv_telemetry")
            if isinstance(cv_meta, dict):
                try:
                    from prometheus.storage.aws_s3 import sync_job_artifacts_to_s3

                    sync_job_artifacts_to_s3(job.id, run_dir, cv_meta)
                except Exception as exc:
                    _LOG.warning("AWS S3 telemetry sync skipped: %s", exc)
            if not public_mode:
                with stage("result_assembly"):
                    shutil.copyfile(source, run_dir / job.source_file)
                if isinstance(cv_meta, dict):
                    if cv_meta.get("clahe_triggered") or (run_dir / "opencv_clahe_enhanced.jpg").is_file():
                        cv_meta["clahe_preview_url"] = f"/api/jobs/{job.id}/frames/opencv_clahe_enhanced.jpg"
                    if cv_meta.get("hud_artifact") or (run_dir / "opencv_hud_overlay.jpg").is_file():
                        cv_meta["hud_preview_url"] = f"/api/jobs/{job.id}/frames/opencv_hud_overlay.jpg"
            else:
                # Production retains prompt/analysis JSON in Postgres, not local media;
                # if Amazon S3 synced the HUD/CLAHE artifacts, serve their 24h pre-signed S3 URLs.
                if "video" in payload:
                    payload["video"].pop("preview_url", None)
                    payload["scenes"] = [
                        {"index": scene["index"], "start": scene["start"], "end": scene["end"],
                         "duration": scene["duration"], "description": scene["description"],
                         "frames": []}
                        for scene in payload["scenes"]
                    ]
                if "image" in payload:
                    payload["image"].pop("preview_url", None)
                if isinstance(cv_meta, dict):
                    aws_s3 = cv_meta.get("aws_s3") if isinstance(cv_meta.get("aws_s3"), dict) else {}
                    if aws_s3.get("clahe_s3_url"):
                        cv_meta["clahe_preview_url"] = aws_s3["clahe_s3_url"]
                    else:
                        cv_meta.pop("clahe_preview_url", None)
                    if aws_s3.get("hud_s3_url"):
                        cv_meta["hud_preview_url"] = aws_s3["hud_s3_url"]
                    else:
                        cv_meta.pop("hud_preview_url", None)
            payload.update({"job_id": job.id, "operation": operation,
                            "notice": "The exact original creator prompt cannot be guaranteed." if operation == "decode" else
                            "A new prompt inspired by the reference, not its original instructions.",
                            "provider": provider})
            with stage("result_persistence"):
                credit_service.save_result(job.id, payload, output_root / job.id)
            result_saved = True
            if wallet is not None:
                with stage("credit_settlement"):
                    credit_service.settle(job.id, True)
            manager.update(job.id, run_dir=None if public_mode else run_dir, state="complete", stage="Complete")
        except Exception:
            if not result_saved:
                shutil.rmtree(output_root / job.id, ignore_errors=True)
                if wallet is not None:
                    with stage("credit_settlement"):
                        credit_service.settle(job.id, False)
            # A durable result remains reserved for restart reconciliation if
            # settlement itself failed. Never release a completed paid result.
            _LOG.exception("Orb %s job failed", operation)
            raise
        finally:
            with stage("cleanup"):
                source.unlink(missing_ok=True)
                if public_mode:
                    shutil.rmtree(output_root / job.id, ignore_errors=True)

    @app.post("/api/orb/{operation}/file", status_code=202)
    async def orb_visual(operation: str, request: Request, file: UploadFile = File(...)) -> dict:
        observe("request_parsed")
        if operation not in {"decode", "compose"}:
            raise HTTPException(status_code=404, detail="Unknown operation.")
        wallet = _authorize_ai(request)
        metric("paid", int(wallet is not None))
        filename, destination = await _save_upload(file, allow_images=True)
        media = await _validate_orb_media(destination)
        observe("set_operation", f"{operation}_{media['kind']}")
        job = manager.create(filename, tier=operation, source_file=f"source{destination.suffix.lower()}")
        try:
            fingerprint = _fingerprint_file(destination, operation) if wallet is not None else ""
            reserved_job_id, is_new = _reserve_paid(wallet, request, operation, fingerprint, job)
            if not is_new:
                metric("reused")
                if current() is not None:
                    current().job_id = reserved_job_id
                manager.remove(job.id)
                destination.unlink(missing_ok=True)
                return {"job_id": reserved_job_id}
            manager.submit(job.id, lambda: _run_orb_visual_job(job, destination, media, operation, wallet))
        except Exception:
            if wallet is not None:
                with stage("credit_settlement"):
                    credit_service.settle(job.id, False)
            manager.remove(job.id)
            destination.unlink(missing_ok=True)
            raise
        return {"job_id": job.id}

    @app.post("/api/orb/enhance", status_code=202)
    async def orb_enhance(request: Request, payload: dict) -> dict:
        observe("request_parsed")
        wallet = _authorize_ai(request)
        metric("paid", int(wallet is not None))
        prompt = payload.get("prompt") if isinstance(payload, dict) else None
        output = payload.get("output", "image") if isinstance(payload, dict) else None
        style = payload.get("style", "") if isinstance(payload, dict) else None
        detail = payload.get("detail", "balanced") if isinstance(payload, dict) else None
        if not isinstance(prompt, str) or not 3 <= len(prompt.strip()) <= 4000:
            raise HTTPException(status_code=422, detail="Prompt must contain 3–4000 characters.")
        if output not in {"image", "video"} or detail not in {"concise", "balanced", "detailed"}:
            raise HTTPException(status_code=422, detail="Invalid output or detail preference.")
        if not isinstance(style, str) or len(style) > 80:
            raise HTTPException(status_code=422, detail="Style must be at most 80 characters.")
        job = manager.create("Text prompt", tier="enhance")
        with stage("file_hash"):
            fingerprint = hashlib.sha256(json.dumps(
                {"prompt": prompt.strip(), "output": output, "style": style.strip(), "detail": detail},
                sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        try:
            reserved_job_id, is_new = _reserve_paid(wallet, request, "enhance", fingerprint, job)
        except Exception:
            manager.remove(job.id)
            raise
        if not is_new:
            metric("reused")
            if current() is not None:
                current().job_id = reserved_job_id
            manager.remove(job.id)
            return {"job_id": reserved_job_id}

        def run() -> None:
            manager.update(job.id, stage="Enhancing prompt")
            result_saved = False
            try:
                enhanced = _orb_service().enhance(prompt.strip(), output, style.strip(), detail)
                run_dir = output_root / job.id
                run_dir.mkdir(parents=True, exist_ok=True)
                result = {"job_id": job.id, "operation": "enhance", "original_prompt": prompt.strip(),
                          "prompt": enhanced, "output": output, "style": style.strip(), "detail": detail,
                          "provider": provider}
                with stage("result_persistence"):
                    credit_service.save_result(job.id, result, output_root / job.id)
                result_saved = True
                if wallet is not None:
                    with stage("credit_settlement"):
                        credit_service.settle(job.id, True)
                manager.update(job.id, run_dir=None if public_mode else run_dir, state="complete", stage="Complete")
            except Exception:
                if not result_saved:
                    shutil.rmtree(output_root / job.id, ignore_errors=True)
                    if wallet is not None:
                        with stage("credit_settlement"):
                            credit_service.settle(job.id, False)
                _LOG.exception("Orb enhance job failed")
                raise
            finally:
                if public_mode:
                    shutil.rmtree(output_root / job.id, ignore_errors=True)

        try:
            manager.submit(job.id, run)
        except Exception:
            if wallet is not None:
                with stage("credit_settlement"):
                    credit_service.settle(job.id, False)
            manager.remove(job.id)
            raise
        return {"job_id": job.id}

    @app.post("/api/analyze", status_code=202)
    async def analyze(
        request: Request,
        file: UploadFile | None = File(default=None),
        upload_id: str | None = Form(default=None),
        source_job_id: str | None = Form(default=None),
        payment_quote_id: str | None = Form(default=None),
        payment_token: str | None = Form(default=None),
    ) -> dict:
        if public_mode:
            raise HTTPException(status_code=404, detail="Unknown operation.")
        if require_payment and not payments_enabled:
            raise HTTPException(status_code=402, detail="AI operations require verified Orb credits. Payments are not available yet.")
        if provider != "mock" and not require_payment:
            if not _local_ai_allowed(request):
                raise HTTPException(status_code=402, detail="Legacy analysis is available only in explicit local testing.")
            _authorize_ai(request)
        if provider == "mock" and not require_payment and not _local_ai_allowed(request):
            raise HTTPException(status_code=402, detail="AI operations require verified credits. Payments are not available yet.")
        if require_payment:
            source_job = manager.get(source_job_id) if source_job_id else None
            if source_job is None or source_job.tier != "basic" or source_job.state != "complete":
                raise HTTPException(status_code=400, detail="A completed basic analysis is required before advanced analysis.")
            source_path = source_job.run_dir / source_job.source_file if source_job.run_dir else None
            if source_path is None or not source_path.is_file():
                raise HTTPException(status_code=404, detail="Basic analysis video file is missing.")
            job = manager.create(video_name=source_job.video_name, tier="advanced", source_file=source_job.source_file)
            try:
                reserved_job_id = payment_service.reserve(
                    payment_quote_id or "", payment_token or "", source_job_id, job.id
                )
            except PaymentError as exc:
                manager.remove(job.id)
                raise HTTPException(status_code=402, detail=str(exc))
            if reserved_job_id != job.id:
                manager.remove(job.id)
                job = manager.get(reserved_job_id)
                if job is None:
                    raise HTTPException(status_code=409, detail="Payment is tied to an analysis job that is unavailable. Do not pay again; restore the server job state.")
                if job.state != "error":
                    return {"job_id": job.id}
                manager.update(job.id, state="processing", stage="Queued", error=None)
            destination = upload_root / f"{uuid.uuid4().hex}{source_path.suffix.lower()}"
            try:
                shutil.copyfile(source_path, destination)
                manager.submit(job.id, lambda: _run_job(job, destination))
            except Exception as exc:
                destination.unlink(missing_ok=True)
                manager.update(job.id, state="error", error=str(exc))
                raise HTTPException(status_code=503, detail=f"Could not start analysis for this payment: {exc}")
            return {"job_id": job.id}

        if file is None and not upload_id:
            raise HTTPException(status_code=400, detail="A staged video upload is required.")

        if upload_id:
            job = manager.create(video_name="Staged video", tier="advanced")
            staged = _take_staged_upload(upload_id)
            if staged is None:
                manager.remove(job.id)
                raise HTTPException(
                    status_code=404,
                    detail="Staged upload is unavailable. Upload the video again.",
                )
            filename, destination = staged
            job.video_name = filename
            job.source_file = f"source{destination.suffix.lower()}"
        else:
            filename, destination = await _save_upload(file)
            await _validate_upload(destination)
            job = manager.create(
                video_name=filename,
                tier="advanced",
                source_file=f"source{destination.suffix.lower()}",
            )

        try:
            manager.submit(job.id, lambda: _run_job(job, destination))
        except Exception:
            manager.remove(job.id)
            destination.unlink(missing_ok=True)
            raise
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}")
    def job_status(request: Request, job_id: str) -> dict:
        paid = _paid_job_owner(request, job_id)
        saved, paid = _recover_paid_result(job_id, paid)
        job = manager.get(job_id)
        if paid and paid["status"] == "consumed" and saved:
            return {"id": job_id, "state": "complete", "tier": paid["operation"],
                    "stage": "Complete", "error": None}
        if job is None:
            if paid is None:
                raise HTTPException(status_code=404, detail="Unknown job.")
            state = "error" if paid["status"] == "released" else "processing"
            return {"id": job_id, "state": state, "tier": paid["operation"],
                    "stage": "Complete" if state == "complete" else "Interrupted",
                    "error": "AI processing failed. Try again with a new request." if state == "error" else None}
        info = manager.public_info(job)
        if paid and paid["status"] == "reserved" and info["state"] == "complete":
            info["state"] = "processing"
            info["stage"] = "Finalizing testnet credit"
        if job.tier in {"decode", "compose", "enhance"} and info["state"] == "error":
            info["error"] = "AI processing failed. Check the server configuration or try again."
        return info

    @app.get("/api/jobs/{job_id}/result")
    def job_result(request: Request, job_id: str) -> dict:
        paid = _paid_job_owner(request, job_id)
        durable_result, paid = _recover_paid_result(job_id, paid)
        job = manager.get(job_id)
        if paid and paid["status"] != "consumed":
            raise HTTPException(status_code=409 if paid["status"] == "reserved" else 502,
                                detail="AI processing is incomplete or failed.")
        if paid and paid["status"] == "consumed" and durable_result is not None:
            return durable_result
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job.")
        if job.state == "error":
            detail = "AI processing failed. Check the server configuration or try again." if job.tier in {"decode", "compose", "enhance"} else job.error or "Analysis failed."
            raise HTTPException(status_code=502, detail=detail)
        if job.state != "complete" and job.run_dir is None:
            raise HTTPException(status_code=409, detail="Analysis is still running.")
        if job.tier == "basic":
            return build_basic_result_dto(
                job.id, job.run_dir, job.video_name, job.source_file
            )
        if job.tier in {"decode", "compose", "enhance"}:
            saved = credit_service.result(job.id, output_root)
            if saved is None:
                raise HTTPException(status_code=503, detail="Orb result is temporarily unavailable.")
            return saved
        return build_result_dto(job.id, job.run_dir, job.video_name, job.source_file)

    @app.post("/api/jobs/{job_id}/remix")
    def job_remix(job_id: str, payload: dict) -> dict:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job.")
        if job.state == "error":
            raise HTTPException(status_code=400, detail=job.error or "Analysis failed.")
        if job.state != "complete" or job.run_dir is None:
            raise HTTPException(status_code=409, detail="Analysis is still running.")
        if job.tier != "advanced":
            raise HTTPException(status_code=403, detail="Remix requires advanced analysis.")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Remix body must be a JSON object.")
        try:
            overrides = {
                str(key): value if isinstance(value, str) else str(value)
                for key, value in payload.items()
            }
            analysis_path = job.run_dir / "analysis.json"
            report = AnalysisReport.from_dict(json.loads(analysis_path.read_text(encoding="utf-8")))
            remixed, applied = apply_remix(report, overrides)
            prompt_markdown = build_reconstructed_prompt(remixed)
        except PrometheusError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"applied": applied, "prompt_markdown": prompt_markdown}

    @app.get("/api/jobs/{job_id}/frames/{file_path:path}")
    def job_frame(request: Request, job_id: str, file_path: str) -> FileResponse:
        paid = _paid_job_owner(request, job_id)
        if public_mode:
            raise HTTPException(status_code=404, detail="Temporary media is not retained.")
        job = manager.get(job_id)
        run_dir = job.run_dir if job else (output_root / job_id if paid and paid["status"] == "consumed" else None)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="Frames not available.")
        base = run_dir.resolve()
        target = (base / file_path).resolve()
        if not target.is_relative_to(base):
            raise HTTPException(status_code=400, detail="Invalid frame path.")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Frame not found.")
        return FileResponse(target)

    if public_mode:
        @app.get("/")
        def api_root() -> dict:
            return {"service": "Orb API"}
    else:
        static_dir = _BUILT_WEB_DIR if _BUILT_WEB_DIR.is_dir() else _WEB_DIR
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="web")
    return app


app = create_app()

try:
    from mangum import Mangum  # type: ignore[import-not-found]

    handler = Mangum(app, lifespan="auto")
except ImportError:  # pragma: no cover - fallback when mangum is not installed
    handler = None  # type: ignore[assignment]
