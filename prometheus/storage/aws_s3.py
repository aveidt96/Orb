"""Amazon S3 (AWS) Telemetry & Diagnostic Artifact Persistence for Orb.

Reads `ORB_AWS_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and
`AWS_REGION` (default `"us-east-1"`) from the environment. When configured,
persists OpenCV 5.0 diagnostic artifacts (`opencv_hud_overlay.jpg`,
`opencv_clahe_enhanced.jpg`, and `opencv_telemetry.json`) to:
    s3://<ORB_AWS_S3_BUCKET>/jobs/<job_id>/<filename>

Designed to be fault-tolerant with short connection/read timeouts so S3 network
hiccups or missing credentials never block or fail an Orb visual analysis job.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

_ARTIFACT_CONTENT_TYPES: dict[str, str] = {
    "opencv_hud_overlay.jpg": "image/jpeg",
    "opencv_clahe_enhanced.jpg": "image/jpeg",
    "opencv_telemetry.json": "application/json",
}


def get_aws_s3_config() -> dict[str, str]:
    """Return normalized AWS S3 configuration from environment variables."""
    bucket = (
        os.environ.get("ORB_AWS_S3_BUCKET", "").strip()
        or os.environ.get("AWS_S3_BUCKET", "").strip()
    )
    region = (
        os.environ.get("AWS_REGION", "").strip()
        or os.environ.get("AWS_DEFAULT_REGION", "").strip()
        or "us-east-1"
    )
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    session_token = os.environ.get("AWS_SESSION_TOKEN", "").strip()
    return {
        "bucket": bucket,
        "region": region,
        "access_key": access_key,
        "secret_key": secret_key,
        "session_token": session_token,
    }


def build_aws_integration_metadata(
    artifacts_synced: list[str] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Build the `aws_integration` telemetry dictionary reported in `opencv_telemetry`."""
    cfg = get_aws_s3_config()
    bucket = cfg["bucket"]
    region = cfg["region"]
    compute_env = os.environ.get("ORB_COMPUTE_ENV", "").strip().upper()
    has_aws_exec = bool(os.environ.get("AWS_EXECUTION_ENV", "").strip())
    s3_enabled = bool(bucket)
    aws_active = s3_enabled or compute_env == "AWS" or has_aws_exec

    services: list[str] = []
    if s3_enabled:
        services.append("Amazon S3")
    if aws_active:
        services.append("AWS Graviton / Compute Ready")

    synced_list = list(artifacts_synced or [])
    payload: dict[str, Any] = {
        "enabled": aws_active,
        "services": services,
        "s3_bucket": bucket,
        "s3_region": region,
        "artifacts_synced": synced_list,
    }
    if bucket and job_id:
        payload["s3_prefix"] = f"s3://{bucket}/jobs/{job_id}/"
    return payload


def _create_boto3_s3_client(cfg: dict[str, str]) -> Any:
    """Create a boto3 S3 client with fast timeouts."""
    import boto3  # type: ignore[import-not-found]

    kwargs: dict[str, Any] = {"region_name": cfg["region"]}
    if cfg["access_key"] and cfg["secret_key"]:
        kwargs["aws_access_key_id"] = cfg["access_key"]
        kwargs["aws_secret_access_key"] = cfg["secret_key"]
    if cfg["session_token"]:
        kwargs["aws_session_token"] = cfg["session_token"]

    try:
        from botocore.config import Config  # type: ignore[import-not-found]

        kwargs["config"] = Config(
            connect_timeout=2,
            read_timeout=3,
            retries={"max_attempts": 1},
        )
    except Exception:
        pass

    return boto3.client("s3", **kwargs)


def _sigv4_sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _put_s3_sigv4_fallback(
    cfg: dict[str, str],
    key: str,
    body: bytes,
    content_type: str,
    timeout: float = 3.0,
) -> None:
    """Zero-dependency AWS Signature Version 4 PUT fallback if boto3 is not installed."""
    bucket = cfg["bucket"]
    region = cfg["region"]
    access_key = cfg["access_key"]
    secret_key = cfg["secret_key"]
    if not (bucket and access_key and secret_key):
        raise RuntimeError("AWS S3 SigV4 fallback requires bucket, access_key, and secret_key.")

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    host = f"{bucket}.s3.{region}.amazonaws.com"
    canonical_uri = "/" + key.lstrip("/")
    payload_hash = hashlib.sha256(body).hexdigest()

    headers: dict[str, str] = {
        "content-type": content_type,
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if cfg["session_token"]:
        headers["x-amz-security-token"] = cfg["session_token"]

    sorted_keys = sorted(headers.keys())
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted_keys)
    signed_headers = ";".join(sorted_keys)
    canonical_request = "\n".join([
        "PUT",
        canonical_uri,
        "",
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{datestamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    k_date = _sigv4_sign(("AWS4" + secret_key).encode("utf-8"), datestamp)
    k_region = _sigv4_sign(k_date, region)
    k_service = _sigv4_sign(k_region, "s3")
    k_signing = _sigv4_sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    url = f"https://{host}{canonical_uri}"
    req = urllib.request.Request(url, data=body, method="PUT")
    for k, v in headers.items():
        if k != "host":
            req.add_header(k, v)
    req.add_header("Authorization", authorization)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status not in (200, 201, 204):
            raise RuntimeError(f"S3 PUT returned HTTP {resp.status}")


def sync_opencv_artifacts_to_s3(
    job_id: str,
    run_dir: Path | str,
    cv_telemetry: dict[str, Any],
    s3_client: Any | None = None,
) -> dict[str, Any]:
    """Write `opencv_telemetry.json` and upload OpenCV artifacts to Amazon S3 if configured.

    Always populates and returns the `aws_integration` metadata dict and attaches
    it to `cv_telemetry["aws_integration"]`.
    """
    target_dir = Path(run_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    cfg = get_aws_s3_config()
    bucket = cfg["bucket"]

    # Always write opencv_telemetry.json into run_dir so it is available locally and for S3 sync
    telemetry_file = target_dir / "opencv_telemetry.json"
    try:
        snapshot = dict(cv_telemetry)
        snapshot["aws_integration"] = build_aws_integration_metadata([], job_id=job_id)
        telemetry_file.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    except Exception as exc:
        _LOG.debug("Could not write local opencv_telemetry.json: %s", exc)

    if not bucket:
        meta = build_aws_integration_metadata([], job_id=job_id)
        cv_telemetry["aws_integration"] = meta
        return meta

    candidate_names = [
        "opencv_hud_overlay.jpg",
        "opencv_clahe_enhanced.jpg",
        "opencv_telemetry.json",
    ]
    existing_files = [
        (name, target_dir / name)
        for name in candidate_names
        if (target_dir / name).is_file()
    ]

    artifacts_synced: list[str] = []
    client = s3_client
    if client is None:
        try:
            client = _create_boto3_s3_client(cfg)
        except Exception:
            client = None

    for name, path in existing_files:
        s3_key = f"jobs/{job_id}/{name}"
        content_type = _ARTIFACT_CONTENT_TYPES.get(name, "application/octet-stream")
        try:
            if client is not None:
                if hasattr(client, "upload_file"):
                    client.upload_file(
                        str(path),
                        bucket,
                        s3_key,
                        ExtraArgs={"ContentType": content_type},
                    )
                else:
                    client.put_object(
                        Bucket=bucket,
                        Key=s3_key,
                        Body=path.read_bytes(),
                        ContentType=content_type,
                    )
            else:
                _put_s3_sigv4_fallback(cfg, s3_key, path.read_bytes(), content_type)
            artifacts_synced.append(name)
        except Exception as exc:
            _LOG.warning("AWS S3 artifact sync skipped for %s: %s", s3_key, exc)

    meta = build_aws_integration_metadata(artifacts_synced, job_id=job_id)
    cv_telemetry["aws_integration"] = meta
    try:
        telemetry_file.write_text(json.dumps(cv_telemetry, indent=2), encoding="utf-8")
    except Exception:
        pass
    return meta
