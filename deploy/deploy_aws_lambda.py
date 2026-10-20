"""Automated AWS Graviton2 (Arm64) Lambda + Function URL deployer for Orb.

Supports two deployment modes:
1. `--mode image`: Builds `Dockerfile.lambda` (`linux/arm64`), pushes to Amazon ECR,
   and deploys `orb-opencv5-api` (`PackageType="Image"`, `Architectures=["arm64"]`,
   `MemorySize=3008`, `Timeout=120`).
2. `--mode zip` (or `--mode auto` when Docker Desktop is not running locally):
   Downloads `manylinux2014_aarch64` Python 3.12 wheels, packages `prometheus/`,
   `web_dist/`, and `config.yaml`, uploads to `s3://<ORB_AWS_S3_BUCKET>/lambda/`,
   and deploys `orb-opencv5-api` (`Runtime="python3.12"`, `Architectures=["arm64"]`,
   `MemorySize=3008`, `Timeout=120`).

In both modes, configures a public HTTPS Function URL (`AuthType="NONE"`) with
CORS enabled for `https://orb-azure-ten.vercel.app` and prints the live URL.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import boto3  # type: ignore[import-not-found]
from botocore.exceptions import ClientError  # type: ignore[import-not-found]

ROOT_DIR = Path(__file__).resolve().parents[1]
FUNCTION_NAME = "orb-opencv5-api"
ECR_REPO_NAME = "orb-opencv5-api"
IAM_ROLE_NAME = "orb-opencv5-lambda-role"


def load_dotenv() -> dict[str, str]:
    """Read `.env` in repo root into `os.environ` without printing secrets."""
    env_path = ROOT_DIR / ".env"
    loaded: dict[str, str] = {}
    if env_path.is_file():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and v:
                loaded[k] = v
                if not os.environ.get(k):
                    os.environ[k] = v
    return loaded


def boto_session() -> boto3.Session:
    load_dotenv()
    region = (
        os.environ.get("AWS_REGION", "").strip()
        or os.environ.get("AWS_DEFAULT_REGION", "").strip()
        or "us-east-1"
    )
    kwargs: dict[str, Any] = {"region_name": region}
    ak = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    sk = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    st = os.environ.get("AWS_SESSION_TOKEN", "").strip()
    if ak and sk:
        kwargs["aws_access_key_id"] = ak
        kwargs["aws_secret_access_key"] = sk
    if st:
        kwargs["aws_session_token"] = st
    return boto3.Session(**kwargs)


def ensure_lambda_role(iam_client: Any) -> str:
    """Ensure `orb-opencv5-lambda-role` exists with BasicExecution + S3 access."""
    assume_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    created = False
    try:
        resp = iam_client.get_role(RoleName=IAM_ROLE_NAME)
        role_arn = resp["Role"]["Arn"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        print(f"[IAM] Creating execution role {IAM_ROLE_NAME}...")
        resp = iam_client.create_role(
            RoleName=IAM_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(assume_policy),
            Description="Execution role for Orb OpenCV 5.0 Arm64 Graviton Lambda API",
        )
        role_arn = resp["Role"]["Arn"]
        created = True

    for policy_arn in (
        "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        "arn:aws:iam::aws:policy/AmazonS3FullAccess",
    ):
        try:
            iam_client.attach_role_policy(RoleName=IAM_ROLE_NAME, PolicyArn=policy_arn)
        except ClientError:
            pass

    if created:
        print("[IAM] Waiting 10s for new IAM role propagation...")
        time.sleep(10)
    return str(role_arn)


def docker_available() -> bool:
    try:
        res = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


def build_and_push_ecr_image(session: boto3.Session, account_id: str) -> str:
    """Build `Dockerfile.lambda` for `linux/arm64` and push to Amazon ECR."""
    region = session.region_name or "us-east-1"
    ecr = session.client("ecr")
    try:
        ecr.describe_repositories(repositoryNames=[ECR_REPO_NAME])
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "RepositoryNotFoundException":
            print(f"[ECR] Creating repository {ECR_REPO_NAME}...")
            ecr.create_repository(
                repositoryName=ECR_REPO_NAME,
                imageScanningConfiguration={"scanOnPush": False},
            )
        else:
            raise

    auth = ecr.get_authorization_token()
    auth_data = auth["authorizationData"][0]
    token_bytes = base64.b64decode(auth_data["authorizationToken"])
    username, password = token_bytes.decode("utf-8").split(":", 1)
    registry = auth_data["proxyEndpoint"].replace("https://", "")
    image_uri = f"{account_id}.dkr.ecr.{region}.amazonaws.com/{ECR_REPO_NAME}:latest"

    print(f"[ECR] Logging into {registry}...")
    subprocess.run(
        ["docker", "login", "--username", username, "--password-stdin", registry],
        input=password.encode("utf-8"),
        check=True,
    )

    print(f"[Docker] Building linux/arm64 Graviton image -> {image_uri}...")
    subprocess.run(
        [
            "docker",
            "buildx",
            "build",
            "--platform",
            "linux/arm64",
            "--provenance=false",
            "-f",
            str(ROOT_DIR / "Dockerfile.lambda"),
            "-t",
            image_uri,
            "--push",
            str(ROOT_DIR),
        ],
        check=True,
    )
    return image_uri


def build_and_upload_arm64_zip(session: boto3.Session, bucket: str) -> str:
    """Build an Arm64 (`manylinux2014_aarch64`) Python 3.12 deployment zip and upload to S3."""
    s3 = session.client("s3")
    s3_key = "lambda/orb-opencv5-api-arm64.zip"

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        pkg_dir = tmp / "package"
        wheels_dir = tmp / "wheels"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        wheels_dir.mkdir(parents=True, exist_ok=True)

        packages = [
            "pyyaml>=6.0",
            "fastapi>=0.115",
            "mangum>=0.19.0",
            "python-multipart>=0.0.9",
            "Pillow>=11.0",
            "eth-account>=0.13,<1",
            "opencv-python-headless>=4.10.0",
            "numpy>=1.26.0",
            "google-genai>=1.0",
            "requests>=2.31.0",
        ]
        print("[Packager] Downloading linux_aarch64 (AWS Graviton Arm64) Python 3.12 wheels...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                " install",
            ][:3]
            + [
                "install",
                "--platform",
                "manylinux2014_aarch64",
                "--implementation",
                "cp",
                "--python-version",
                "3.12",
                "--only-binary=:all:",
                "--target",
                str(pkg_dir),
                "--no-compile",
                "--quiet",
                *packages,
            ],
            check=True,
        )

        # Copy Orb application code
        shutil.copytree(
            ROOT_DIR / "prometheus",
            pkg_dir / "prometheus",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        if (ROOT_DIR / "web_dist").is_dir():
            shutil.copytree(ROOT_DIR / "web_dist", pkg_dir / "web_dist")
        if (ROOT_DIR / "web").is_dir():
            shutil.copytree(
                ROOT_DIR / "web",
                pkg_dir / "web",
                ignore=shutil.ignore_patterns("*.test.js"),
            )
        if (ROOT_DIR / "config.yaml").is_file():
            shutil.copy2(ROOT_DIR / "config.yaml", pkg_dir / "config.yaml")

        # Trim unnecessary __pycache__ directories inside site-packages while preserving .dist-info metadata
        for pattern in ("__pycache__",):
            for p in list(pkg_dir.rglob(pattern)):
                if p.is_dir() and "prometheus" not in p.parts:
                    shutil.rmtree(p, ignore_errors=True)

        zip_path = tmp / "orb-opencv5-api-arm64.zip"
        print("[Packager] Compressing Arm64 Lambda bundle...")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in pkg_dir.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, file_path.relative_to(pkg_dir).as_posix())

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"[S3] Uploading {size_mb:.1f} MB bundle to s3://{bucket}/{s3_key}...")
        s3.upload_file(str(zip_path), bucket, s3_key)

    return s3_key


def wait_until_lambda_ready(lambda_client: Any, fn_name: str) -> None:
    for _ in range(45):
        cfg = lambda_client.get_function_configuration(FunctionName=fn_name)
        state = cfg.get("State")
        update_status = cfg.get("LastUpdateStatus")
        if state == "Active" and update_status in (None, "Successful"):
            return
        if state == "Failed" or update_status == "Failed":
            raise RuntimeError(
                f"Lambda state failed: {cfg.get('StateReason')} / {cfg.get('LastUpdateStatusReason')}"
            )
        time.sleep(2)


def lambda_env_vars(bucket: str) -> dict[str, str]:
    gemini_key = (
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
        or os.environ.get("PROMETHEUS_API_KEY", "").strip()
    )
    variables = {
        "ORB_ENV": "local",
        "ORB_COMPUTE_ENV": "AWS",
        "ORB_SERVERLESS_SYNC": "1",
        "ORB_AWS_S3_BUCKET": bucket,
        "ORB_JUDGE_DEMO_CODE": os.environ.get("ORB_JUDGE_DEMO_CODE", "OPENCV2026").strip() or "OPENCV2026",
        "ORB_JUDGE_DAILY_CAP": os.environ.get("ORB_JUDGE_DAILY_CAP", "150").strip() or "150",
        "ORB_JUDGE_IP_DAILY_LIMIT": "25",
        "ORB_CREDITS_ENABLED": "1",
        "ORB_PUBLIC_ORIGIN": "https://orb-azure-ten.vercel.app",
        "PROMETHEUS_CORS_ORIGINS": "https://orb-azure-ten.vercel.app,http://localhost:5173,http://127.0.0.1:8000",
        "ORB_ARBITRUM_RPC_URL": os.environ.get(
            "ORB_ARBITRUM_RPC_URL", "https://sepolia-rollup.arbitrum.io/rpc"
        ).strip(),
        "ORB_TREASURY_ADDRESS": os.environ.get(
            "ORB_TREASURY_ADDRESS", "0xc855D21175D81C852E657169424FA974171394F1"
        ).strip(),
        "ORB_CREDIT_RECEIVER": os.environ.get(
            "ORB_CREDIT_RECEIVER", "0xc855D21175D81C852E657169424FA974171394F1"
        ).strip(),
        "ORB_AI_PROVIDER": "gemini",
        "ORB_AI_MODEL": os.environ.get("ORB_AI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash",
    }
    if gemini_key:
        variables["GEMINI_API_KEY"] = gemini_key
    return variables


def ensure_function_url(lambda_client: Any, fn_name: str) -> str:
    try:
        resp = lambda_client.get_function_url_config(FunctionName=fn_name)
        url = resp["FunctionUrl"]
        lambda_client.update_function_url_config(
            FunctionName=fn_name,
            AuthType="NONE",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            resp = lambda_client.create_function_url_config(
                FunctionName=fn_name,
                AuthType="NONE",
            )
            url = resp["FunctionUrl"]
        else:
            raise

    for sid, action, extra in (
        (
            "OrbPublicFunctionUrlInvoke",
            "lambda:InvokeFunctionUrl",
            {"FunctionUrlAuthType": "NONE"},
        ),
        (
            "OrbPublicFunctionInvoke",
            "lambda:InvokeFunction",
            {"InvokedViaFunctionUrl": True},
        ),
    ):
        try:
            lambda_client.add_permission(
                FunctionName=fn_name,
                StatementId=sid,
                Action=action,
                Principal="*",
                **extra,
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceConflictException":
                print(f"[Lambda] Permission note ({sid}): {exc}")

    return str(url)


def deploy(mode: str = "auto", skip_upload: bool = False) -> str:
    session = boto_session()
    sts = session.client("sts")
    ident = sts.get_caller_identity()
    account_id = ident["Account"]
    region = session.region_name or "us-east-1"
    bucket = (
        os.environ.get("ORB_AWS_S3_BUCKET", "").strip()
        or "orb-opencv5-vision-2026"
    )
    print(f"[AWS] Authenticated as Account {account_id} in {region} (S3 bucket: {bucket})")

    iam = session.client("iam")
    role_arn = ensure_lambda_role(iam)
    lambda_client = session.client("lambda")
    env_vars = lambda_env_vars(bucket)

    use_image = mode == "image" or (mode == "auto" and docker_available())

    exists = False
    existing_pkg_type = None
    try:
        fn_info = lambda_client.get_function(FunctionName=FUNCTION_NAME)
        exists = True
        existing_pkg_type = fn_info["Configuration"].get("PackageType")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    if exists and (
        (use_image and existing_pkg_type != "Image")
        or (not use_image and existing_pkg_type != "Zip")
    ):
        print(f"[Lambda] Replacing {existing_pkg_type} function with {'Image' if use_image else 'Zip'}...")
        lambda_client.delete_function(FunctionName=FUNCTION_NAME)
        time.sleep(3)
        exists = False

    def _call_with_memory_fallback(fn, **kwargs):
        for mem in (3008, 1024, 512):
            try:
                return fn(MemorySize=mem, **kwargs)
            except ClientError as exc:
                if "MemorySize" in str(exc) and mem != 512:
                    print(f"[Lambda] Account memory limit < {mem} MB; falling back to {512 if mem == 1024 else 1024} MB...")
                    continue
                raise

    if use_image:
        image_uri = build_and_push_ecr_image(session, account_id)
        if not exists:
            print(f"[Lambda] Creating Graviton2 Arm64 container function {FUNCTION_NAME}...")
            _call_with_memory_fallback(
                lambda_client.create_function,
                FunctionName=FUNCTION_NAME,
                Role=role_arn,
                PackageType="Image",
                Code={"ImageUri": image_uri},
                Architectures=["arm64"],
                Timeout=120,
                Environment={"Variables": env_vars},
            )
        else:
            print(f"[Lambda] Updating Graviton2 Arm64 container function {FUNCTION_NAME}...")
            wait_until_lambda_ready(lambda_client, FUNCTION_NAME)
            lambda_client.update_function_code(
                FunctionName=FUNCTION_NAME,
                ImageUri=image_uri,
                Architectures=["arm64"],
            )
            wait_until_lambda_ready(lambda_client, FUNCTION_NAME)
            _call_with_memory_fallback(
                lambda_client.update_function_configuration,
                FunctionName=FUNCTION_NAME,
                Role=role_arn,
                Timeout=120,
                Environment={"Variables": env_vars},
            )
    else:
        s3_key = (
            "lambda/orb-opencv5-api-arm64.zip"
            if skip_upload
            else build_and_upload_arm64_zip(session, bucket)
        )
        if not exists:
            print(f"[Lambda] Creating Graviton2 Arm64 function {FUNCTION_NAME}...")
            for attempt in range(5):
                try:
                    _call_with_memory_fallback(
                        lambda_client.create_function,
                        FunctionName=FUNCTION_NAME,
                        Runtime="python3.12",
                        Role=role_arn,
                        Handler="prometheus.api.app.handler",
                        Code={"S3Bucket": bucket, "S3Key": s3_key},
                        Architectures=["arm64"],
                        Timeout=120,
                        Environment={"Variables": env_vars},
                    )
                    break
                except ClientError as exc:
                    if "cannot be assumed" in str(exc) and attempt < 4:
                        time.sleep(5)
                    else:
                        raise
        else:
            print(f"[Lambda] Updating Graviton2 Arm64 function {FUNCTION_NAME}...")
            wait_until_lambda_ready(lambda_client, FUNCTION_NAME)
            if not skip_upload:
                lambda_client.update_function_code(
                    FunctionName=FUNCTION_NAME,
                    S3Bucket=bucket,
                    S3Key=s3_key,
                    Architectures=["arm64"],
                )
                wait_until_lambda_ready(lambda_client, FUNCTION_NAME)
            _call_with_memory_fallback(
                lambda_client.update_function_configuration,
                FunctionName=FUNCTION_NAME,
                Role=role_arn,
                Handler="prometheus.api.app.handler",
                Timeout=120,
                Environment={"Variables": env_vars},
            )

    wait_until_lambda_ready(lambda_client, FUNCTION_NAME)
    fn_url = ensure_function_url(lambda_client, FUNCTION_NAME)
    print("\n============================================================")
    print(f"LIVE AWS GRAVITON2 (ARM64) LAMBDA FUNCTION URL:\n{fn_url}")
    print("============================================================")
    return fn_url


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy Orb OpenCV 5.0 API to AWS Lambda Arm64")
    parser.add_argument(
        "--mode",
        choices=["auto", "image", "zip"],
        default="auto",
        help="Deployment mode: 'image' (Docker + ECR), 'zip' (aarch64 wheels via S3), or 'auto'",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Reuse existing s3://<bucket>/lambda/orb-opencv5-api-arm64.zip",
    )
    args = parser.parse_args()
    deploy(args.mode, skip_upload=args.skip_upload)
