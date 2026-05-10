"""Shared helpers for the minio-provisioner operator."""

from __future__ import annotations

import base64
import os
import secrets
import string

import kopf
import kubernetes
from minio import Minio, MinioAdmin
from minio.credentials import StaticProvider
from minio.error import S3Error
from minio.versioningconfig import ENABLED, VersioningConfig

MINIO_ENDPOINT = os.environ["MINIO_ENDPOINT"]
MINIO_ACCESS_KEY = os.environ["MINIO_ACCESS_KEY"]
MINIO_SECRET_KEY = os.environ["MINIO_SECRET_KEY"]
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"

CRD_GROUP = "minio.sonne.zone"
CRD_VERSION = "v1"

# Built-in MinIO policy names accepted by MinioUser.spec.policy
BUILTIN_POLICIES: frozenset[str] = frozenset(
    {"readwrite", "readonly", "writeonly", "diagnostics", "consoleAdmin"}
)

# MinIO endpoint exposed to consumers (written into K8s secrets)
MINIO_ENDPOINT_URL = f"{'https' if MINIO_SECURE else 'http'}://{MINIO_ENDPOINT}"


# ---------------------------------------------------------------------------
# MinIO client factories
# ---------------------------------------------------------------------------


def minio_client(
    endpoint: str = MINIO_ENDPOINT,
    access_key: str = MINIO_ACCESS_KEY,
    secret_key: str = MINIO_SECRET_KEY,
    *,
    secure: bool = MINIO_SECURE,
) -> Minio:
    """Return a MinIO client for bucket operations."""
    return Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )


def admin_client(
    endpoint: str = MINIO_ENDPOINT,
    access_key: str = MINIO_ACCESS_KEY,
    secret_key: str = MINIO_SECRET_KEY,
    *,
    secure: bool = MINIO_SECURE,
) -> MinioAdmin:
    """Return a MinioAdmin client for user/policy operations."""
    return MinioAdmin(
        endpoint=endpoint,
        credentials=StaticProvider(access_key, secret_key),
        secure=secure,
    )


# ---------------------------------------------------------------------------
# Random credential generation
# ---------------------------------------------------------------------------


def rand_secret_key(length: int = 40) -> str:
    """Generate a random MinIO-compatible secret key."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------------
# Kubernetes Secret helpers
# ---------------------------------------------------------------------------


def get_existing_secret_data(
    namespace: str,
    secret_name: str,
) -> dict[str, str] | None:
    """Read all decoded key/value pairs from an existing Kubernetes Secret.

    Returns None if the secret does not exist.  Raises TemporaryError on
    unexpected Kubernetes API failures.
    """
    v1 = kubernetes.client.CoreV1Api()
    try:
        secret = v1.read_namespaced_secret(name=secret_name, namespace=namespace)
        return {k: base64.b64decode(v).decode() for k, v in (secret.data or {}).items()}
    except kubernetes.client.exceptions.ApiException as exc:
        if exc.status == 404:
            return None
        raise kopf.TemporaryError(
            f"Failed reading secret {namespace}/{secret_name}: {exc}",
            delay=15,
        ) from exc


def ensure_secret(
    namespace: str,
    secret_name: str,
    body: kopf.Body,
    data: dict[str, str],
    logger: kopf.Logger,
) -> None:
    """Create or update a Kubernetes Secret with the supplied data.

    Skips the patch if the secret already exists with identical values to
    avoid churning the secret's resourceVersion.

    Owner references are only set when the CR and secret share the same
    namespace; cross-namespace owner refs are not permitted by Kubernetes.
    """
    v1 = kubernetes.client.CoreV1Api()
    secret_body = kubernetes.client.V1Secret(
        metadata=kubernetes.client.V1ObjectMeta(name=secret_name),
        string_data=data,
    )
    cr_namespace = body["metadata"]["namespace"]
    if namespace == cr_namespace:
        kopf.adopt(secret_body)

    try:
        v1.create_namespaced_secret(namespace=namespace, body=secret_body)
        logger.info("Created secret %s/%s", namespace, secret_name)
    except kubernetes.client.exceptions.ApiException as exc:
        if exc.status == 409:
            existing = v1.read_namespaced_secret(name=secret_name, namespace=namespace)
            existing_data = {
                k: base64.b64decode(v).decode()
                for k, v in (existing.data or {}).items()
            }
            if existing_data == data:
                logger.debug(
                    "Secret %s/%s already up-to-date, skipping patch",
                    namespace,
                    secret_name,
                )
                return
            v1.patch_namespaced_secret(
                name=secret_name,
                namespace=namespace,
                body={"stringData": data},
            )
            logger.info("Updated existing secret %s/%s", namespace, secret_name)
        else:
            raise kopf.TemporaryError(
                f"Kubernetes API error creating secret "
                f"{namespace}/{secret_name}: {exc}",
                delay=15,
            ) from exc


def delete_secret(
    namespace: str,
    secret_name: str,
    logger: kopf.Logger,
) -> None:
    """Delete a Kubernetes Secret, silently ignoring 404."""
    v1 = kubernetes.client.CoreV1Api()
    try:
        v1.delete_namespaced_secret(name=secret_name, namespace=namespace)
        logger.info("Deleted secret %s/%s", namespace, secret_name)
    except kubernetes.client.exceptions.ApiException as exc:
        if exc.status == 404:
            logger.debug("Secret %s/%s already absent", namespace, secret_name)
        else:
            raise kopf.TemporaryError(
                f"Failed deleting secret {namespace}/{secret_name}: {exc}",
                delay=15,
            ) from exc


# ---------------------------------------------------------------------------
# Bucket helpers
# ---------------------------------------------------------------------------


def bucket_exists(client: Minio, name: str) -> bool:
    """Return True if the bucket exists."""
    try:
        return client.bucket_exists(name)
    except S3Error as exc:
        raise kopf.TemporaryError(
            f"MinIO error checking bucket {name!r}: {exc}",
            delay=30,
        ) from exc


def ensure_bucket(client: Minio, name: str, logger: kopf.Logger) -> None:
    """Create the bucket if it does not exist."""
    try:
        if not client.bucket_exists(name):
            client.make_bucket(name)
            logger.info("Created bucket %r", name)
        else:
            logger.debug("Bucket %r already exists", name)
    except S3Error as exc:
        raise kopf.TemporaryError(
            f"MinIO error ensuring bucket {name!r}: {exc}",
            delay=30,
        ) from exc


def set_bucket_versioning(
    client: Minio,
    name: str,
    enabled: bool,  # noqa: FBT001
    logger: kopf.Logger,
) -> None:
    """Enable or disable versioning on a bucket."""
    try:
        status = ENABLED if enabled else "Suspended"
        client.set_bucket_versioning(name, VersioningConfig(status))
        logger.debug("Set versioning=%s on bucket %r", status, name)
    except S3Error as exc:
        raise kopf.TemporaryError(
            f"MinIO error setting versioning on {name!r}: {exc}",
            delay=30,
        ) from exc


def get_bucket_versioning_enabled(client: Minio, name: str) -> bool:
    """Return True if versioning is currently enabled on the bucket."""
    try:
        config = client.get_bucket_versioning(name)
        return getattr(config, "status", None) == ENABLED
    except S3Error as exc:
        raise kopf.TemporaryError(
            f"MinIO error reading versioning for {name!r}: {exc}",
            delay=30,
        ) from exc
