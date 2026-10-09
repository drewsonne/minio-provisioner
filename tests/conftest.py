"""Let controller/common.py import without a live MinIO."""

from __future__ import annotations

import os

os.environ.setdefault("MINIO_ENDPOINT", "minio.test:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "test")
