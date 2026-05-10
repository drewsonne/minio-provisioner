"""Kopf handlers for the MinioUser CRD."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import kopf
from common import (
    BUILTIN_POLICIES,
    CRD_GROUP,
    CRD_VERSION,
    MINIO_ENDPOINT_URL,
    admin_client,
    delete_secret,
    ensure_secret,
    get_existing_secret_data,
    rand_secret_key,
)
from minio.error import S3Error

if TYPE_CHECKING:
    from minio import MinioAdmin


# ---------------------------------------------------------------------------
# MinIO admin API helpers
# ---------------------------------------------------------------------------


def _user_exists(client: MinioAdmin, access_key: str) -> bool:
    """Return True if the MinIO user exists."""
    try:
        client.get_user(access_key)
    except S3Error as exc:
        if exc.code in ("XMinioAdminNoSuchUser", "NoSuchUser"):
            return False
        raise kopf.TemporaryError(
            f"MinIO error checking user {access_key!r}: {exc}",
            delay=30,
        ) from exc
    else:
        return True


def _ensure_user(
    client: MinioAdmin,
    access_key: str,
    secret_key: str,
    logger: kopf.Logger,
) -> None:
    """Create or update the MinIO user with the given credentials."""
    try:
        if _user_exists(client, access_key):
            client.update_user(access_key, secret_key)
            logger.debug("Updated credentials for MinIO user %r", access_key)
        else:
            client.add_user(access_key, secret_key)
            logger.info("Created MinIO user %r", access_key)
    except S3Error as exc:
        raise kopf.TemporaryError(
            f"MinIO error upserting user {access_key!r}: {exc}",
            delay=30,
        ) from exc


def _attach_policy(
    client: MinioAdmin,
    access_key: str,
    policy: str,
    logger: kopf.Logger,
) -> None:
    """Attach the named policy to the MinIO user."""
    if policy not in BUILTIN_POLICIES:
        raise kopf.PermanentError(
            f"Unknown policy {policy!r}. Allowed values: {sorted(BUILTIN_POLICIES)}"
        )
    try:
        client.attach_policy(policy, user=access_key)
        logger.info("Attached policy %r to MinIO user %r", policy, access_key)
    except S3Error as exc:
        raise kopf.TemporaryError(
            f"MinIO error attaching policy {policy!r} to {access_key!r}: {exc}",
            delay=30,
        ) from exc


def _upsert_user(
    spec: kopf.Spec,
    body: kopf.Body,
    name: str,
    namespace: str,
    logger: kopf.Logger,
) -> dict[str, Any]:
    """Converge MinIO user state to match spec. Returns status dict."""
    policy: str = spec["policy"]
    secret_name: str = spec["secretName"]
    secret_ns: str = spec.get("secretNamespace", namespace)

    # Preserve existing secret_key to avoid rotating credentials on every reconcile.
    existing = get_existing_secret_data(secret_ns, secret_name)
    secret_key: str = (existing or {}).get("secret_key") or rand_secret_key()

    client = admin_client()
    _ensure_user(client, name, secret_key, logger)
    _attach_policy(client, name, policy, logger)

    ensure_secret(
        secret_ns,
        secret_name,
        body,
        {
            "access_key": name,
            "secret_key": secret_key,
            "endpoint": MINIO_ENDPOINT_URL,
        },
        logger,
    )

    return {"accessKey": name, "policy": policy, "ready": True}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@kopf.on.create(
    CRD_GROUP, CRD_VERSION, "miniousers", retries=5, backoff=30, timeout=300
)
def create_fn(
    spec: kopf.Spec,
    body: kopf.Body,
    name: str,
    namespace: str,
    logger: kopf.Logger,
    **_: Any,
) -> dict[str, Any]:
    return _upsert_user(spec, body, name, namespace, logger)


@kopf.on.resume(CRD_GROUP, CRD_VERSION, "miniousers")
def resume_fn(
    spec: kopf.Spec,
    body: kopf.Body,
    name: str,
    namespace: str,
    logger: kopf.Logger,
    **_: Any,
) -> dict[str, Any]:
    return _upsert_user(spec, body, name, namespace, logger)


@kopf.on.update(
    CRD_GROUP, CRD_VERSION, "miniousers", field="spec", retries=3, backoff=15
)
def update_fn(
    spec: kopf.Spec,
    body: kopf.Body,
    name: str,
    namespace: str,
    logger: kopf.Logger,
    **_: Any,
) -> dict[str, Any]:
    return _upsert_user(spec, body, name, namespace, logger)


@kopf.on.delete(
    CRD_GROUP, CRD_VERSION, "miniousers", retries=3, backoff=15, timeout=120
)
def delete_fn(
    spec: kopf.Spec,
    name: str,
    namespace: str,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    secret_name: str = spec["secretName"]
    secret_ns: str = spec.get("secretNamespace", namespace)

    client = admin_client()
    try:
        if _user_exists(client, name):
            client.remove_user(name)
            logger.info("Deleted MinIO user %r", name)
        else:
            logger.info("MinIO user %r already absent", name)
    except S3Error as exc:
        raise kopf.TemporaryError(
            f"MinIO error deleting user {name!r}: {exc}",
            delay=30,
        ) from exc

    delete_secret(secret_ns, secret_name, logger)


@kopf.timer(
    CRD_GROUP,
    CRD_VERSION,
    "miniousers",
    interval=300,
    initial_delay=60,
    idle=30,
)
def check_drift(
    spec: kopf.Spec,
    body: kopf.Body,
    name: str,
    namespace: str,
    logger: kopf.Logger,
    **_: Any,
) -> dict[str, Any] | None:
    """Detect and remediate out-of-band changes to the MinIO user."""
    client = admin_client()
    if not _user_exists(client, name):
        logger.warning("Drift detected: user %r is missing — recreating", name)
        result = _upsert_user(spec, body, name, namespace, logger)
        return {**result, "drift": True, "driftReason": "missing"}

    return None
