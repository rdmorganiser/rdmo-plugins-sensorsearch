from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest

import requests

from rdmo_sensorsearch import client
from rdmo_sensorsearch.contracts import BackendFailure, BackendSuccess
from rdmo_sensorsearch.services.performance import capture_performance
from rdmo_sensorsearch.transport import TransportError, request_json


@pytest.mark.parametrize("kind", ("http", "timeout", "connection", "json"))
def test_client_failures_raise_transport_error_and_keep_request_options(monkeypatch, kind):
    calls = []
    response = SimpleNamespace(status_code=503 if kind == "http" else 200, text="unavailable")
    error = {
        "http": requests.HTTPError("unavailable", response=response),
        "timeout": requests.Timeout("timeout"),
        "connection": requests.ConnectionError("connection lost"),
        "json": ValueError("invalid JSON"),
    }[kind]

    def fail():
        raise error

    response.raise_for_status = fail if kind == "http" else lambda: None
    response.json = fail if kind == "json" else lambda: {}

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if kind in ("timeout", "connection"):
            raise error
        return response

    monkeypatch.setattr(client.requests, "get", get)
    monkeypatch.setattr(client, "get_user_agent", lambda: "sensorsearch-test")
    monkeypatch.setattr(client, "get_request_timeout", lambda: 7)
    with capture_performance() as record, pytest.raises(TransportError) as failure:
        client.fetch_json("https://backend.example/data", auth_token="token")

    assert str(failure.value) == str(error)
    assert failure.value.url == "https://backend.example/data"
    assert failure.value.status_code == (response.status_code if kind in ("http", "json") else None)
    assert calls == [
        (
            "https://backend.example/data",
            {"headers": {"User-Agent": "sensorsearch-test", "Authorization": "Bearer token"}, "timeout": 7},
        )
    ]
    assert record.as_dict()["counts"]["http.error"] == 1


def test_adapter_translation_does_not_swallow_programming_errors_or_mutate_documents():
    def failing(*args, **kwargs):
        raise TransportError("unavailable")

    assert request_json(failing, "url", None) == BackendFailure(("unavailable",))
    document = {"records": []}
    result = request_json(lambda *args, **kwargs: document, "url", None)
    assert result == BackendSuccess(document)
    result.value["records"].append("changed")
    assert document == {"records": []}

    def bug(*args, **kwargs):
        raise ValueError("bug")

    with pytest.raises(ValueError, match="bug"):
        request_json(bug, "url", None)


def test_cached_failures_are_token_scoped_and_retry_in_a_new_refresh(monkeypatch):
    calls = []

    def fetch(url, auth_token=None):
        calls.append((url, auth_token))
        raise TransportError("unavailable")

    monkeypatch.setattr(client, "_fetch_json_uncached", fetch)
    with capture_performance() as record:
        with client.deduplicate_json_requests():
            for token in ("first", "first", "second"):
                with pytest.raises(TransportError, match="unavailable"):
                    client.fetch_json("url", auth_token=token)
        with client.deduplicate_json_requests(), pytest.raises(TransportError):
            client.fetch_json("url", auth_token="first")
    assert calls == [("url", "first"), ("url", "second"), ("url", "first")]
    assert record.as_dict()["counts"]["http.requested"] == 4
    assert record.as_dict()["counts"]["http.cache_hit"] == 1


@pytest.mark.parametrize("error_class", (TransportError, RuntimeError))
def test_concurrent_failure_releases_waiters_and_only_transport_errors_are_cached(monkeypatch, error_class):
    started = Event()
    release = Event()
    calls = []

    def fetch(url, auth_token=None):
        calls.append(url)
        started.set()
        assert release.wait(5)
        raise error_class("unavailable")

    monkeypatch.setattr(client, "_fetch_json_uncached", fetch)
    with capture_performance() as record, client.deduplicate_json_requests(), ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(copy_context().run, client.fetch_json, "url")
        try:
            assert started.wait(5)
            waiter = executor.submit(copy_context().run, client.fetch_json, "url")
            deadline = monotonic() + 5
            while record.as_dict()["counts"].get("http.shared_wait", 0) == 0 and monotonic() < deadline:
                Event().wait(0.001)
            assert record.as_dict()["counts"].get("http.shared_wait") == 1
        finally:
            release.set()
        for future in (owner, waiter):
            with pytest.raises(error_class, match="unavailable"):
                future.result(timeout=5)
        with pytest.raises(error_class):
            client.fetch_json("url")
    assert len(calls) == (1 if error_class is TransportError else 2)


@pytest.mark.parametrize("payload", (None, {}, []))
def test_empty_json_responses_are_cached(monkeypatch, payload):
    calls = []
    monkeypatch.setattr(client, "_fetch_json_uncached", lambda *args, **kwargs: calls.append(1) or payload)
    with client.deduplicate_json_requests():
        assert client.fetch_json("url") == payload
        assert client.fetch_json("url") == payload
    assert calls == [1]
