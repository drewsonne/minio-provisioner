"""Kopf handlers for the MinioBucket CRD."""

from __future__ import annotations

from typing import Any

import kopf
from common import (
    CRD_GROUP,
    CRD_VERSION,
    ensure_bucket,
    get_bucket_versioning_enabled,
    minio_client,
    set_bucket_versioning,
)


def _upsert_bucket(spec: kopf.Spec, name: str, logger: kopf.Logger) -> None:
    """Ensure the MinIO bucket exists and matches the desired spec."""
    versioning: bool = bool(spec.get("versioning", False))

    client = minio_client()
    ensure_bucket(client, name, logger)
    set_bucket_versioning(client, name, versioning, logger)


def _bucket_matches_spec(spec: kopf.Spec, name: str) -> bool:
    """Return True if the live bucket already matches the desired spec."""
    versioning: bool = bool(spec.get("versioning", False))
    client = minio_client()
    return get_bucket_versioning_enabled(client, name) == versioning


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@kopf.on.create(
    CRD_GROUP, CRD_VERSION, "miniobuckets", retries=5, backoff=30, timeout=300
)
def create_fn(
    spec: kopf.Spec,
    name: str,
    logger: kopf.Logger,
    **_: Any,
) -> dict[str, Any]:
    _upsert_bucket(spec, name, logger)
    return {"bucket": name, "ready": True}


@kopf.on.resume(CRD_GROUP, CRD_VERSION, "miniobuckets")
def resume_fn(
    spec: kopf.Spec,
    name: str,
    logger: kopf.Logger,
    **_: Any,
) -> dict[str, Any]:
    _upsert_bucket(spec, name, logger)
    return {"bucket": name, "ready": True}


@kopf.on.update(
    CRD_GROUP, CRD_VERSION, "miniobuckets", field="spec", retries=3, backoff=15
)
def update_fn(
    spec: kopf.Spec,
    name: str,
    logger: kopf.Logger,
    **_: Any,
) -> dict[str, Any]:
    _upsert_bucket(spec, name, logger)
    return {"bucket": name, "ready": True}


@kopf.on.delete(
    CRD_GROUP, CRD_VERSION, "miniobuckets", retries=3, backoff=15, timeout=120
)
def delete_fn(
    name: str,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    """Log bucket deletion — the bucket itself is intentionally NOT removed.

    Deleting a MinioBucket CR removes the K8s resource but preserves the
    actual MinIO bucket and its data to prevent accidental data loss.
    """
    logger.info(
        "MinioBucket CR %r deleted — MinIO bucket preserved to prevent data loss",
        name,
    )


@kopf.timer(
    CRD_GROUP,
    CRD_VERSION,
    "miniobuckets",
    interval=300,
    initial_delay=60,
    idle=30,
)
def check_drift(
    spec: kopf.Spec,
    name: str,
    logger: kopf.Logger,
    **_: Any,
) -> dict[str, Any] | None:
    """Detect and remediate out-of-band changes to the bucket."""
    client = minio_client()
    from common import bucket_exists

    if not bucket_exists(client, name):
        logger.warning("Drift detected: bucket %r is missing — recreating", name)
        _upsert_bucket(spec, name, logger)
        return {"bucket": name, "ready": True, "drift": True, "driftReason": "missing"}

    if not _bucket_matches_spec(spec, name):
        logger.warning("Drift detected: bucket %r config mismatch — remediating", name)
        _upsert_bucket(spec, name, logger)
        return {
            "bucket": name,
            "ready": True,
            "drift": True,
            "driftReason": "config mismatch",
        }

    return None
