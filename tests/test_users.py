"""Tests for MinioUser policy attachment."""

from __future__ import annotations

import logging
import threading
import time
from unittest.mock import MagicMock

import kopf
import pytest
import users
from minio.error import MinioAdminException

ALREADY_APPLIED_BODY = (
    '{"Code":"XMinioAdminPolicyChangeAlreadyApplied",'
    '"Message":"The specified policy change is already in effect."}'
)

LOGGER = logging.getLogger("test")


def test_attach_policy_already_applied_is_success() -> None:
    client = MagicMock()
    client.attach_policy.side_effect = MinioAdminException("400", ALREADY_APPLIED_BODY)
    users._attach_policy(client, "alice", "readwrite", LOGGER)


def test_attach_policy_other_admin_error_is_temporary() -> None:
    client = MagicMock()
    client.attach_policy.side_effect = MinioAdminException(
        "500", '{"Code":"XMinioServerNotInitialized"}'
    )
    with pytest.raises(kopf.TemporaryError):
        users._attach_policy(client, "alice", "readwrite", LOGGER)


def test_upsert_users_serialize_admin_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    # Each encrypted admin call runs a 64 MiB argon2id KDF; overlapping calls
    # OOM the pod, so admin calls must never run concurrently.
    active = 0
    peak = 0
    guard = threading.Lock()

    def admin_call(*_: object, **__: object) -> None:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with guard:
            active -= 1

    client = MagicMock()
    client.user_info.side_effect = admin_call
    client.user_add.side_effect = admin_call
    client.attach_policy.side_effect = admin_call
    monkeypatch.setattr(users, "admin_client", lambda: client)
    monkeypatch.setattr(users, "get_existing_secret_data", lambda *_: None)
    monkeypatch.setattr(users, "ensure_secret", lambda *_: None)

    spec = {"policy": "readwrite", "secretName": "creds"}
    body = {"metadata": {"namespace": "ns"}}
    threads = [
        threading.Thread(
            target=users._upsert_user, args=(spec, body, f"u{i}", "ns", LOGGER)
        )
        for i in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak == 1
