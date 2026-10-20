"""Amazon S3 (AWS) Telemetry, Serverless Job State & Diagnostic Artifact Persistence for Orb.

Reads `ORB_AWS_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and
`AWS_REGION` (default `"us-east-1"`) from the environment (or `.env` in the
repository root). When configured, uploads OpenCV 5.0 diagnostic artifacts
(`opencv_hud_overlay.jpg`, `opencv_clahe_enhanced.jpg`, and
`opencv_telemetry.json`) and serverless job state (`job_state.json`) to:
    s3://<ORB_AWS_S3_BUCKET>/orb-jobs/<job_id>/<filename>
auto-creating the bucket if it does not yet exist, and generates 24-hour
pre-signed S3 URLs (`hud_s3_url`, `clahe_s3_url`).

Designed to be fault-tolerant with a 4-second timeout so S3 network hiccups or
missing credentials never block or fail an Orb visual analysis job.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)
_ROOT_DIR = Path(__file__).resolve().parents[2]

_ARTIFACT_CONTENT_TYPES: dict[str, str] = {
    "opencv_hud_overlay.jpg": "image/jpeg",
    "opencv_clahe_enhanced.jpg": "image/jpeg",
    "opencv_telemetry.json": "application/json",
    "job_state.json": "application/json",
}

_PRESIGNED_EXPIRES_SECONDS = 86400  # 24 hours
_VERIFIED_BUCKETS: set[str] = set()


def _running_under_pytest() -> bool:
    return bool(
        "PYTEST_CURRENT_TEST" in os.environ
        or "PYTEST_VERSION" in os.environ
        or "pytest" in sys.modules
    )


def load_dotenv_aws_vars(dotenv_path: Path | None = None) -> None:
    """Load AWS / S3 variables from `.env` in repo root without overwriting set env vars."""
    if _running_under_pytest() and dotenv_path is None:
        return
    env_file = dotenv_path or (_ROOT_DIR / ".env")
    if not env_file.is_file():
        return
    aws_keys = {
        "ORB_AWS_S3_BUCKET",
        "AWS_S3_BUCKET",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "ORB_COMPUTE_ENV",
    }
    try:
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key in aws_keys and val and not os.environ.get(key):
                os.environ[key] = val
    except OSError:
        pass


def get_aws_s3_config() -> dict[str, str]:
    """Return normalized AWS S3 configuration from environment variables."""
    load_dotenv_aws_vars()
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


def _has_aws_credentials(cfg: dict[str, str], s3_client: Any | None = None) -> bool:
    if _running_under_pytest() and s3_client is None and os.environ.get("ORB_ALLOW_PYTEST_LIVE_S3") != "1":
        return False
    return bool(
        s3_client is not None
        or (cfg["access_key"] and cfg["secret_key"])
        or os.environ.get("AWS_EXECUTION_ENV", "").strip()
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "").strip()
    )


def build_aws_integration_metadata(
    artifacts_synced: list[str] | None = None,
    job_id: str | None = None,
    keys: list[str] | None = None,
    hud_s3_url: str | None = None,
    clahe_s3_url: str | None = None,
) -> dict[str, Any]:
    """Build the `aws_integration` telemetry dictionary reported in `opencv_telemetry`."""
    cfg = get_aws_s3_config()
    bucket = cfg["bucket"]
    region = cfg["region"]
    compute_env = os.environ.get("ORB_COMPUTE_ENV", "").strip().upper()
    has_aws_exec = bool(
        os.environ.get("AWS_EXECUTION_ENV", "").strip()
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "").strip()
    )
    s3_enabled = bool(bucket)
    aws_active = s3_enabled or compute_env == "AWS" or has_aws_exec

    services: list[str] = []
    if s3_enabled:
        services.append("Amazon S3")
    if has_aws_exec:
        services.append("AWS Lambda (Arm64 Graviton)")
    elif aws_active:
        services.append("AWS Graviton / Compute Ready")

    synced_list = list(artifacts_synced or [])
    payload: dict[str, Any] = {
        "enabled": aws_active,
        "synced": bool(synced_list),
        "services": services,
        "s3_bucket": bucket,
        "s3_region": region,
        "artifacts_synced": synced_list,
    }
    if keys is not None:
        payload["keys"] = list(keys)
    if hud_s3_url:
        payload["hud_s3_url"] = hud_s3_url
    if clahe_s3_url:
        payload["clahe_s3_url"] = clahe_s3_url
    if bucket and job_id:
        payload["s3_prefix"] = f"s3://{bucket}/orb-jobs/{job_id}/"
    return payload


def _create_boto3_s3_client(cfg: dict[str, str]) -> Any:
    """Create a boto3 S3 client with a 4-second timeout."""
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
            connect_timeout=4,
            read_timeout=4,
            retries={"max_attempts": 1},
            signature_version="s3v4",
        )
    except Exception:
        pass

    return boto3.client("s3", **kwargs)


def _ensure_bucket_exists(client: Any, bucket: str, region: str) -> None:
    """Attempt to create the S3 bucket if it does not exist yet."""
    if not client or bucket in _VERIFIED_BUCKETS or not hasattr(client, "create_bucket"):
        return
    try:
        if region == "us-east-1":
            client.create_bucket(Bucket=bucket)
        else:
            client.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        _VERIFIED_BUCKETS.add(bucket)
    except Exception as exc:
        err_text = str(exc)
        if "BucketAlreadyOwnedByYou" in err_text or "BucketAlreadyExists" in err_text:
            _VERIFIED_BUCKETS.add(bucket)
        else:
            _LOG.debug("create_bucket(%s) returned: %s", bucket, exc)


def _sigv4_sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _presign_s3_sigv4_fallback(
    cfg: dict[str, str],
    key: str,
    expires_in: int = _PRESIGNED_EXPIRES_SECONDS,
) -> str | None:
    """Generate a SigV4 pre-signed GET URL when boto3 is not used."""
    bucket = cfg["bucket"]
    region = cfg["region"]
    access_key = cfg["access_key"]
    secret_key = cfg["secret_key"]
    if not (bucket and access_key and secret_key):
        return None

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    host = f"{bucket}.s3.{region}.amazonaws.com"
    canonical_uri = "/" + key.lstrip("/")
    credential_scope = f"{datestamp}/{region}/s3/aws4_request"

    query_params: dict[str, str] = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{access_key}/{credential_scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires_in),
        "X-Amz-SignedHeaders": "host",
    }
    if cfg["session_token"]:
        query_params["X-Amz-Security-Token"] = cfg["session_token"]

    sorted_qp = sorted(query_params.items())
    canonical_querystring = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted_qp
    )
    canonical_headers = f"host:{host}\n"
    canonical_request = "\n".join([
        "GET",
        canonical_uri,
        canonical_querystring,
        canonical_headers,
        "host",
        "UNSIGNED-PAYLOAD",
    ])
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    k_date = _sigv4_sign(("AWS4" + secret_key).encode("utf-8"), datestamp)
    k_region = _sigv4_sign(k_date, region)
    k_service = _sigv4_sign(k_region, "s3")
    k_signing = _sigv4_sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"https://{host}{canonical_uri}?{canonical_querystring}&X-Amz-Signature={signature}"


def _put_s3_sigv4_fallback(
    cfg: dict[str, str],
    key: str,
    body: bytes,
    content_type: str,
    timeout: float = 4.0,
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


def _generate_presigned_get_url(
    client: Any | None,
    cfg: dict[str, str],
    bucket: str,
    key: str,
) -> str | None:
    if client is not None and hasattr(client, "generate_presigned_url"):
        try:
            return str(
                client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=_PRESIGNED_EXPIRES_SECONDS,
                )
            )
        except Exception as exc:
            _LOG.debug("Could not generate boto3 presigned URL for %s: %s", key, exc)
    return _presign_s3_sigv4_fallback(cfg, key)


def _upload_single_object(
    client: Any | None,
    cfg: dict[str, str],
    bucket: str,
    s3_key: str,
    path: Path,
    content_type: str,
) -> None:
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


def save_serverless_job_state_to_s3(
    job_id: str,
    job_state: dict[str, Any],
    s3_client: Any | None = None,
) -> bool:
    """Persist serialized job state + result JSON to `s3://<bucket>/orb-jobs/<job_id>/job_state.json`."""
    cfg = get_aws_s3_config()
    bucket = cfg["bucket"]
    if not (bucket and _has_aws_credentials(cfg, s3_client)):
        return False
    s3_key = f"orb-jobs/{job_id}/job_state.json"
    body = json.dumps(job_state, indent=2).encode("utf-8")
    client = s3_client
    if client is None:
        try:
            client = _create_boto3_s3_client(cfg)
        except Exception:
            client = None
    try:
        if client is not None and hasattr(client, "put_object"):
            try:
                client.put_object(
                    Bucket=bucket,
                    Key=s3_key,
                    Body=body,
                    ContentType="application/json",
                )
            except Exception as first_exc:
                if "NoSuchBucket" in str(first_exc) or "404" in str(first_exc):
                    _ensure_bucket_exists(client, bucket, cfg["region"])
                    client.put_object(
                        Bucket=bucket,
                        Key=s3_key,
                        Body=body,
                        ContentType="application/json",
                    )
                else:
                    raise
        else:
            _put_s3_sigv4_fallback(cfg, s3_key, body, "application/json")
        return True
    except Exception as exc:
        _LOG.debug("Could not persist serverless job_state.json for %s: %s", job_id, exc)
        return False


def load_serverless_job_state_from_s3(
    job_id: str,
    s3_client: Any | None = None,
) -> dict[str, Any] | None:
    """Fallback-read `s3://<bucket>/orb-jobs/<job_id>/job_state.json` across warm Lambda containers."""
    cfg = get_aws_s3_config()
    bucket = cfg["bucket"]
    if not (bucket and _has_aws_credentials(cfg, s3_client)):
        return None
    s3_key = f"orb-jobs/{job_id}/job_state.json"
    client = s3_client
    if client is None:
        try:
            client = _create_boto3_s3_client(cfg)
        except Exception:
            client = None
    try:
        if client is not None and hasattr(client, "get_object"):
            resp = client.get_object(Bucket=bucket, Key=s3_key)
            raw = resp["Body"].read()
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else None
        url = _presign_s3_sigv4_fallback(cfg, s3_key, expires_in=60)
        if url:
            with urllib.request.urlopen(url, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, dict) else None
    except Exception as exc:
        _LOG.debug("Could not load serverless job_state.json for %s: %s", job_id, exc)
    return None


def load_serverless_frame_from_s3(
    job_id: str,
    filename: str,
    s3_client: Any | None = None,
) -> tuple[bytes, str] | None:
    """Fallback-read `s3://<bucket>/orb-jobs/<job_id>/<filename>` across warm Lambda containers."""
    safe_name = Path(filename).name
    if safe_name not in _ARTIFACT_CONTENT_TYPES:
        return None
    cfg = get_aws_s3_config()
    bucket = cfg["bucket"]
    if not (bucket and _has_aws_credentials(cfg, s3_client)):
        return None
    s3_key = f"orb-jobs/{job_id}/{safe_name}"
    content_type = _ARTIFACT_CONTENT_TYPES[safe_name]
    client = s3_client
    if client is None:
        try:
            client = _create_boto3_s3_client(cfg)
        except Exception:
            client = None
    try:
        if client is not None and hasattr(client, "get_object"):
            resp = client.get_object(Bucket=bucket, Key=s3_key)
            return resp["Body"].read(), content_type
        url = _presign_s3_sigv4_fallback(cfg, s3_key, expires_in=60)
        if url:
            with urllib.request.urlopen(url, timeout=4.0) as resp:
                return resp.read(), content_type
    except Exception as exc:
        _LOG.debug("Could not load serverless frame %s for %s: %s", safe_name, job_id, exc)
    return None


def sync_job_artifacts_to_s3(
    job_id: str,
    run_dir: Path | str,
    telemetry: dict[str, Any],
    s3_client: Any | None = None,
) -> dict[str, Any]:
    """Upload OpenCV 5.0 job artifacts to `s3://<bucket>/orb-jobs/<job_id>/` and generate 24h pre-signed URLs.

    Attaches `telemetry["aws_s3"]` and `telemetry["aws_integration"]` in-place
    and returns `telemetry["aws_s3"]`.
    """
    target_dir = Path(run_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    cfg = get_aws_s3_config()
    bucket = cfg["bucket"]
    region = cfg["region"]
    has_creds = _has_aws_credentials(cfg, s3_client)

    # Always write opencv_telemetry.json into run_dir first
    telemetry_file = target_dir / "opencv_telemetry.json"
    try:
        snapshot = dict(telemetry)
        telemetry_file.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    except Exception as exc:
        _LOG.debug("Could not write initial local opencv_telemetry.json: %s", exc)

    if not (bucket and has_creds):
        aws_s3_meta: dict[str, Any] = {
            "enabled": False,
            "synced": False,
            "bucket": bucket,
            "region": region,
            "keys": [],
            "hud_s3_url": None,
            "clahe_s3_url": None,
        }
        telemetry["aws_s3"] = aws_s3_meta
        telemetry["aws_integration"] = build_aws_integration_metadata([], job_id=job_id)
        return aws_s3_meta

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
    uploaded_keys: list[str] = []
    hud_s3_url: str | None = None
    clahe_s3_url: str | None = None
    last_error: str | None = None

    client = s3_client
    if client is None:
        try:
            client = _create_boto3_s3_client(cfg)
        except Exception:
            client = None

    for name, path in existing_files:
        s3_key = f"orb-jobs/{job_id}/{name}"
        content_type = _ARTIFACT_CONTENT_TYPES.get(name, "application/octet-stream")
        try:
            try:
                _upload_single_object(client, cfg, bucket, s3_key, path, content_type)
            except Exception as first_exc:
                if "NoSuchBucket" in str(first_exc) or "404" in str(first_exc):
                    _ensure_bucket_exists(client, bucket, region)
                    _upload_single_object(client, cfg, bucket, s3_key, path, content_type)
                else:
                    raise
            _VERIFIED_BUCKETS.add(bucket)
            artifacts_synced.append(name)
            uploaded_keys.append(s3_key)
            if name == "opencv_hud_overlay.jpg":
                hud_s3_url = _generate_presigned_get_url(client, cfg, bucket, s3_key)
            elif name == "opencv_clahe_enhanced.jpg":
                clahe_s3_url = _generate_presigned_get_url(client, cfg, bucket, s3_key)
        except Exception as exc:
            last_error = str(exc)
            _LOG.warning("AWS S3 artifact sync skipped for %s: %s", s3_key, exc)

    synced_ok = bool(uploaded_keys)
    aws_s3_meta = {
        "enabled": True,
        "synced": synced_ok,
        "bucket": bucket,
        "region": region,
        "keys": uploaded_keys,
        "hud_s3_url": hud_s3_url,
        "clahe_s3_url": clahe_s3_url,
    }
    if last_error and not synced_ok:
        aws_s3_meta["error"] = last_error
    telemetry["aws_s3"] = aws_s3_meta
    telemetry["aws_integration"] = build_aws_integration_metadata(
        artifacts_synced,
        job_id=job_id,
        keys=uploaded_keys,
        hud_s3_url=hud_s3_url,
        clahe_s3_url=clahe_s3_url,
    )
    try:
        telemetry_file.write_text(json.dumps(telemetry, indent=2), encoding="utf-8")
    except Exception:
        pass
    return aws_s3_meta


def sync_opencv_artifacts_to_s3(
    job_id: str,
    run_dir: Path | str,
    cv_telemetry: dict[str, Any],
    s3_client: Any | None = None,
) -> dict[str, Any]:
    """Alias wrapper around `sync_job_artifacts_to_s3` returning `aws_integration`."""
    sync_job_artifacts_to_s3(job_id, run_dir, cv_telemetry, s3_client=s3_client)
    return cv_telemetry["aws_integration"]
