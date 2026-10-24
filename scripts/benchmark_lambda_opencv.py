"""Authorized live Decode benchmark: one judge grant, no automatic POST retries.

Uses the ordinary deployed pipeline, not a debug endpoint or a locally timed
substitute. Output contains timings/job IDs, never session tokens or signed URLs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import uuid

import cv2
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deploy.deploy_aws_lambda import boto_session
from scripts.benchmark_opencv import _make_standard_image, _make_underexposed_image

BASE = "https://jsnwiqkw5sqs3c7hag6ywd3ngm0vljpc.lambda-url.us-east-1.on.aws"
ORIGIN = "https://orb-azure-ten.vercel.app"
BUCKET = "orb-opencv5-vision-2026"
FUNCTION = "orb-opencv5-api"
RECOVERY_KEYS = ("post_clahe_edge_density", "edge_density_gain_pct",
                 "post_clahe_laplacian_variance", "sharpness_gain_pct")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.output.parent.is_dir() or args.output.exists():
        parser.error("Output parent must exist and the report must be new (prevents duplicate runs).")
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "status": "started",
              "iterations_per_workload": args.iterations, "samples": [], "health": []}

    def save():
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")

    # This journal is written before any grant/media POST. Never rerun it blindly.
    save()
    aws = boto_session()
    client, s3 = aws.client("lambda"), aws.client("s3")
    config = client.get_function_configuration(FunctionName=FUNCTION)
    assert config["Architectures"] == ["arm64"] and config["State"] == "Active"
    assert client.get_function_url_config(FunctionName=FUNCTION)["FunctionUrl"].rstrip("/") == BASE
    report["deployment"] = {k: config[k] for k in ("FunctionName", "Architectures", "Runtime",
                              "MemorySize", "Timeout", "CodeSha256", "LastModified")}
    http = requests.Session()  # Default adapters do not retry failed POSTs.
    http.headers["Origin"] = ORIGIN

    def get(path, **kwargs):
        response = http.get(BASE + path, timeout=40, **kwargs)
        response.raise_for_status()
        return response

    bodies = []
    for path in ("/health", "/api/health", "/api/ready"):
        started = time.perf_counter()
        response = get(path)
        report["health"].append({"path": path, "status": response.status_code,
                                 "round_trip_ms": round((time.perf_counter() - started) * 1000, 1)})
        bodies.append(response.json())
    assert bodies[0] == bodies[1] and bodies[0]["status"] == "ok"
    assert get("/api/orb/credits/config").json()["judge_demo_enabled"] is False
    assert get("/api/orb/credits/config?judge=OPENCV2026").json()["judge_demo_enabled"] is True
    response = http.post(BASE + "/api/orb/judge-session", json={"code": "OPENCV2026"}, timeout=40)
    response.raise_for_status()
    session = response.json()
    auth = {"Authorization": "Bearer " + session["token"]}
    initial = get("/api/orb/credits/balance", headers=auth).json()
    assert initial["available"] >= 2 * args.iterations and initial["consumed"] == 0
    report["initial_balance"] = {k: initial[k] for k in ("available", "granted", "consumed", "reserved")}
    save()

    try:
        with tempfile.TemporaryDirectory(prefix="orb-lambda-benchmark-") as folder:
            for workload, factory in (("1080p_standard", _make_standard_image),
                                      ("1080p_underexposed", _make_underexposed_image)):
                path = Path(folder) / (workload + ".jpg")
                assert cv2.imwrite(str(path), factory(1920, 1080))
                source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                for iteration in range(args.iterations):
                    key = uuid.uuid4().hex
                    report["pending_attempt"] = {"workload": workload, "iteration": iteration + 1,
                                                 "idempotency_key": key}
                    save()
                    started = time.perf_counter()
                    with path.open("rb") as media:
                        response = http.post(BASE + "/api/orb/decode/file?upload_attempt_id=" + key,
                            headers={**auth, "X-Orb-Idempotency-Key": key},
                            files={"file": (path.name, media, "image/jpeg")}, timeout=150)
                    response.raise_for_status()
                    job = response.json()["job_id"]
                    report["pending_attempt"]["job_id"] = job
                    save()
                    deadline = time.monotonic() + 150
                    while True:
                        state = get("/api/jobs/" + job, headers=auth).json()
                        if state["state"] == "error":
                            raise RuntimeError("Live Decode failed; media POST will not be retried.")
                        if state["state"] == "complete":
                            break
                        if time.monotonic() > deadline:
                            raise TimeoutError("Polling expired; media POST will not be retried.")
                        time.sleep(1)
                    result = get("/api/jobs/" + job + "/result", headers=auth).json()
                    result_ms = (time.perf_counter() - started) * 1000
                    cv = result["opencv_telemetry"]
                    assert cv["compute_arch"] == "ARM64" and cv["opencv_version"] == "5.0.0"
                    assert result["image"]["width"] == 1920 and result["image"]["height"] == 1080
                    assert cv["clahe_applied"] == (workload == "1080p_underexposed")
                    required = {"opencv_hud_overlay.jpg", "opencv_telemetry.json", "job_state.json"}
                    if cv["clahe_applied"]:
                        required.add("opencv_clahe_enhanced.jpg")
                        for field in RECOVERY_KEYS:
                            assert cv[field] == cv["clahe_recovery"][field]
                    else:
                        assert all(cv[field] is None for field in RECOVERY_KEYS)
                    artifacts = []
                    for filename in sorted(required):
                        meta = s3.head_object(Bucket=BUCKET, Key=f"orb-jobs/{job}/{filename}")
                        assert meta["ContentLength"] > 0
                        artifacts.append({"name": filename, "bytes": meta["ContentLength"]})
                    balance = get("/api/orb/credits/balance", headers=auth).json()
                    consumed = len(report["samples"]) + 1
                    assert balance["consumed"] == consumed and balance["reserved"] == 0
                    assert balance["available"] == initial["available"] - consumed
                    sample = {"workload": workload, "iteration": iteration + 1, "job_id": job,
                        "source_sha256": source_hash, "width": 1920, "height": 1080,
                        "processing_ms": cv["processing_ms"], "upload_to_result_ms": round(result_ms, 1),
                        "opencv_version": cv["opencv_version"], "compute_runtime": cv["compute_runtime"],
                        "clahe_applied": cv["clahe_applied"], "clahe_recovery": cv["clahe_recovery"],
                        "geometry": cv["sharpness_and_geometry"], "artifacts": artifacts,
                        "balance": {k: balance[k] for k in ("available", "consumed", "reserved")}}
                    report["samples"].append(sample)
                    report.pop("pending_attempt")
                    save()
                    print(json.dumps(sample), flush=True)
        report["summary"] = {}
        for workload in ("1080p_standard", "1080p_underexposed"):
            rows = [s for s in report["samples"] if s["workload"] == workload]
            values = [s["processing_ms"] for s in rows]
            report["summary"][workload] = {"runs": len(values), "mean_ms": round(statistics.mean(values), 3),
                "min_ms": min(values), "max_ms": max(values),
                "mean_upload_to_result_ms": round(statistics.mean(s["upload_to_result_ms"] for s in rows), 1)}
        assert client.get_function_configuration(FunctionName=FUNCTION)["CodeSha256"] == config["CodeSha256"]
        report["status"] = "complete"
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save()
        print(json.dumps(report["summary"], indent=2), flush=True)
    except Exception:
        report["status"] = "incomplete_do_not_resubmit_without_inspection"
        save()
        raise


if __name__ == "__main__":
    main()
