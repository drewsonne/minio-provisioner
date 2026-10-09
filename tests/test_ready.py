"""Every reconcile handler reports readiness where the Ready column reads it."""

from __future__ import annotations

import logging

import buckets
import kopf
import pytest
import users

LOGGER = logging.getLogger("test")


@pytest.mark.parametrize("handler", ["create_fn", "resume_fn", "update_fn"])
def test_user_handlers_set_status_ready(
    handler: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(users, "_upsert_user", lambda *_: {"ready": True})
    patch = kopf.Patch()
    getattr(users, handler)(
        spec={}, body={}, name="u", namespace="ns", logger=LOGGER, patch=patch
    )
    assert patch.status["ready"] is True


@pytest.mark.parametrize("handler", ["create_fn", "resume_fn", "update_fn"])
def test_bucket_handlers_set_status_ready(
    handler: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(buckets, "_upsert_bucket", lambda *_: None)
    patch = kopf.Patch()
    getattr(buckets, handler)(spec={}, name="b", logger=LOGGER, patch=patch)
    assert patch.status["ready"] is True
