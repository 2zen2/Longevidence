import httpx
import pytest

from app.ingestion.http import ApiClient, RetryableHTTPError


def make(max_attempts=4):
    return ApiClient("https://x.test", per_second=1000, max_attempts=max_attempts, backoff_initial=0.001,
                     client=httpx.Client(base_url="https://x.test"))


def test_retries_429_then_succeeds(httpx_mock):
    httpx_mock.add_response(status_code=429, headers={"Retry-After": "0"})
    httpx_mock.add_response(status_code=503)
    httpx_mock.add_response(json={"ok": True})
    api = make()
    assert api.get("/a").json() == {"ok": True}
    assert api.attempts_made == 3


def test_gives_up_after_max_attempts(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(status_code=500)
    api = make(max_attempts=3)
    with pytest.raises(RetryableHTTPError):
        api.get("/a")
    assert api.attempts_made == 3


def test_does_not_retry_client_errors(httpx_mock):
    httpx_mock.add_response(status_code=404)
    api = make()
    assert api.get("/a").status_code == 404
    assert api.attempts_made == 1


def test_retries_network_errors(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectTimeout("slow"))
    httpx_mock.add_response(json={"ok": 1})
    api = make()
    assert api.get("/a").json() == {"ok": 1}
