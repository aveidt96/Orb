"""Storage integrations for Orb (AWS S3 telemetry and artifact persistence)."""

from prometheus.storage.aws_s3 import (
    build_aws_integration_metadata,
    get_aws_s3_config,
    sync_opencv_artifacts_to_s3,
)

__all__ = [
    "build_aws_integration_metadata",
    "get_aws_s3_config",
    "sync_opencv_artifacts_to_s3",
]
