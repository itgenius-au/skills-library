import http.client
import io
import json
import urllib.error
from email.message import Message

import pytest

import _asana


FAKE_TOKEN = "fake-asana-token"


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class RawResponse(FakeResponse):
    def __init__(self, payload):
        self.payload = payload


class RaisingBody:
    def __init__(self, error):
        self.error = error

    def read(self):
        raise self.error

    def close(self):
        pass


def http_error(code, retry_after=None, body=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(
        "https://example.test/resource",
        code,
        "synthetic error",
        headers,
        body if body is not None else io.BytesIO(b'{"errors":[]}'),
    )


def install_router(monkeypatch, outcomes):
    calls = []
    outcomes = iter(outcomes)

    def urlopen(request, timeout=None):
        calls.append((request, timeout))
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(_asana.urllib.request, "urlopen", urlopen)
    return calls


@pytest.fixture(autouse=True)
def reset_transport(monkeypatch):
    waits = []
    monkeypatch.setattr(_asana, "_TOTAL_SLEEP", 0, raising=False)
    monkeypatch.setattr(_asana, "_sleep", waits.append, raising=False)
    return waits


def test_get_retries_429_honours_retry_after_and_uses_timeout(
    monkeypatch, reset_transport
):
    calls = install_router(
        monkeypatch,
        [http_error(429, retry_after=7), FakeResponse({"data": {"gid": "task-1"}})],
    )

    result = _asana.request("GET", "/tasks/task-1", FAKE_TOKEN)

    assert result == {"data": {"gid": "task-1"}}
    assert [timeout for _, timeout in calls] == [30, 30]
    assert reset_transport == [7]


def test_post_retries_429_with_default_wait(monkeypatch, reset_transport):
    calls = install_router(
        monkeypatch,
        [http_error(429), FakeResponse({"data": {"gid": "task-2"}})],
    )

    result = _asana.request(
        "POST",
        "/tasks",
        FAKE_TOKEN,
        data={"data": {"name": "Synthetic task"}},
    )

    assert result == {"data": {"gid": "task-2"}}
    assert len(calls) == 2
    assert reset_transport == [1]


def test_get_retries_5xx_with_backoff(monkeypatch, reset_transport):
    calls = install_router(
        monkeypatch,
        [
            http_error(500),
            http_error(502),
            http_error(503),
            http_error(504),
            FakeResponse({"data": []}),
        ],
    )

    assert _asana.request("GET", "/tasks", FAKE_TOKEN) == {"data": []}
    assert len(calls) == 5
    assert reset_transport == [2, 4, 8, 16]


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("synthetic connection loss"),
        TimeoutError("synthetic timeout"),
        http.client.HTTPException("synthetic protocol failure"),
        ConnectionError("synthetic connection failure"),
    ],
    ids=["url-error", "timeout", "http-exception", "connection-error"],
)
def test_get_retries_lost_response(monkeypatch, reset_transport, error):
    calls = install_router(
        monkeypatch,
        [error, FakeResponse({"data": {"gid": "task-3"}})],
    )

    assert _asana.request("GET", "/tasks/task-3", FAKE_TOKEN) == {
        "data": {"gid": "task-3"}
    }
    assert len(calls) == 2
    assert reset_transport == [2]


def test_get_retries_truncated_json_response(monkeypatch, reset_transport):
    calls = install_router(
        monkeypatch,
        [RawResponse(b'{"data":'), FakeResponse({"data": {"gid": "task-3"}})],
    )

    assert _asana.request("GET", "/tasks/task-3", FAKE_TOKEN) == {
        "data": {"gid": "task-3"}
    }
    assert len(calls) == 2
    assert reset_transport == [2]


def test_get_retries_truncated_multibyte_utf8_response(
    monkeypatch, reset_transport
):
    calls = install_router(
        monkeypatch,
        [
            RawResponse(b'{"data":{"name":"Caf\xc3'),
            FakeResponse({"data": {"name": "Caf\u00e9"}}),
        ],
    )

    assert _asana.request("GET", "/tasks/task-3", FAKE_TOKEN) == {
        "data": {"name": "Caf\u00e9"}
    }
    assert len(calls) == 2
    assert reset_transport == [2]


def test_get_503_retries_when_error_body_read_fails(
    monkeypatch, reset_transport
):
    calls = install_router(
        monkeypatch,
        [
            http_error(503, body=RaisingBody(TimeoutError("body unavailable"))),
            FakeResponse({"data": []}),
        ],
    )

    assert _asana.request("GET", "/tasks", FAKE_TOKEN) == {"data": []}
    assert len(calls) == 2
    assert reset_transport == [2]


def test_post_429_retries_when_error_body_read_fails(
    monkeypatch, reset_transport
):
    calls = install_router(
        monkeypatch,
        [
            http_error(
                429,
                retry_after=3,
                body=RaisingBody(TimeoutError("body unavailable")),
            ),
            FakeResponse({"data": {"gid": "task-2"}}),
        ],
    )

    assert _asana.request(
        "POST",
        "/tasks",
        FAKE_TOKEN,
        data={"data": {"name": "Synthetic task"}},
    ) == {"data": {"gid": "task-2"}}
    assert len(calls) == 2
    assert reset_transport == [3]


@pytest.mark.parametrize(
    "error",
    [
        http_error(503),
        urllib.error.URLError("synthetic connection loss"),
        TimeoutError("synthetic timeout"),
        http.client.HTTPException("synthetic protocol failure"),
        ConnectionError("synthetic connection failure"),
        json.JSONDecodeError("synthetic truncated JSON", "{", 1),
        UnicodeDecodeError("utf-8", b"\xc3", 0, 1, "synthetic truncated UTF-8"),
    ],
    ids=[
        "http-5xx",
        "url-error",
        "timeout",
        "http-exception",
        "connection-error",
        "json-decode-error",
        "unicode-decode-error",
    ],
)
def test_post_does_not_retry_uncertain_failure(
    monkeypatch, reset_transport, error
):
    calls = install_router(monkeypatch, [error])

    with pytest.raises(type(error)) as caught:
        _asana.request(
            "POST",
            "/tasks",
            FAKE_TOKEN,
            data={"data": {"name": "Synthetic task"}},
        )

    assert caught.value is error
    assert len(calls) == 1
    assert reset_transport == []


def test_total_wait_cap_refuses_sleep_and_chains_failure(
    monkeypatch, reset_transport
):
    monkeypatch.setattr(_asana, "_TOTAL_SLEEP", 599)
    error = http_error(429, retry_after=2)
    calls = install_router(monkeypatch, [error])

    with pytest.raises(RuntimeError, match="sleep limit") as caught:
        _asana.request("GET", "/tasks", FAKE_TOKEN)

    assert caught.value.__cause__ is error
    assert len(calls) == 1
    assert reset_transport == []
    assert _asana._TOTAL_SLEEP == 599


def test_retry_limit_is_five_attempts_and_chains_last_failure(
    monkeypatch, reset_transport
):
    errors = [ConnectionResetError(f"synthetic reset {index}") for index in range(5)]
    calls = install_router(monkeypatch, errors)

    with pytest.raises(RuntimeError, match="5 attempts") as caught:
        _asana.request("GET", "/tasks", FAKE_TOKEN)

    assert caught.value.__cause__ is errors[-1]
    assert len(calls) == 5
    assert reset_transport == [2, 4, 8, 16]
