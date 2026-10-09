"""Tests for MinioUser policy attachment."""

from __future__ import annotations

import logging
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
