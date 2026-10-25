"""Tests for the JSON log formatter."""

from __future__ import annotations

import json
import logging

import logs


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        "kopf.objects", logging.INFO, "f.py", 1, "hi %s", ("x",), None
    )
    record.__dict__.update(extra)
    return record


def test_record_is_one_line_with_workgraph_keys() -> None:
    line = logs.JsonFormatter().format(_record())
    assert "\n" not in line
    entry = json.loads(line)
    assert set(entry) == {"time", "level", "logger", "message"}
    assert entry["level"] == "INFO"
    assert entry["logger"] == "kopf.objects"
    assert entry["message"] == "hi x"


def test_exc_with_exc_info() -> None:
    error = ValueError("boom")
    record = _record(exc_info=(ValueError, error, error.__traceback__))
    entry = json.loads(logs.JsonFormatter().format(record))
    assert "ValueError: boom" in entry["exc"]


def test_object_from_k8s_ref() -> None:
    namespaced = _record(k8s_ref={"name": "b", "namespace": "ns"})
    cluster = _record(k8s_ref={"name": "b", "namespace": None})
    assert json.loads(logs.JsonFormatter().format(namespaced))["object"] == "ns/b"
    assert json.loads(logs.JsonFormatter().format(cluster))["object"] == "b"


def test_configure_logging_installs_one_json_handler() -> None:
    root = logging.getLogger()
    saved = root.handlers[:]
    try:
        root.addHandler(logging.NullHandler())
        logs.configure_logging()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, logs.JsonFormatter)
    finally:
        root.handlers[:] = saved
