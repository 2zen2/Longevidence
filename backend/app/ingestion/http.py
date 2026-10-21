"""HTTP client shared by NCBI and OpenAlex: client-side rate limit + retry with backoff.

Retry policy: network errors, timeouts, 429 and 5xx are retried with exponential backoff + jitter
(honouring Retry-After). Other 4xx are programming/input errors and are raised immediately.
"""
import threading
import time

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential, wait_random
from tenacity.wait import wait_base

USER_AGENT = "Longevidence/0.1 (research proof of concept)"


class RetryableHTTPError(Exception):
    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class RateLimiter:
    def __init__(self, per_second: float):
        self.min_interval = 1.0 / per_second
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.min_interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


class _WaitRespectingRetryAfter(wait_base):
    def __init__(self, fallback):
        self.fallback = fallback

    def __call__(self, retry_state):
        exc = retry_state.outcome.exception()
        if isinstance(exc, RetryableHTTPError) and exc.retry_after:
            return min(exc.retry_after, 60.0)
        return self.fallback(retry_state)


class ApiClient:
    def __init__(self, base_url: str, per_second: float, *, client: httpx.Client | None = None,
                 max_attempts: int = 5, backoff_initial: float = 1.0):
        self.client = client or httpx.Client(base_url=base_url, timeout=30,
                                             headers={"User-Agent": USER_AGENT})
        self.limiter = RateLimiter(per_second)
        self.max_attempts = max_attempts
        self.backoff_initial = backoff_initial
        self.attempts_made = 0  # exposed for tests/observability

    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: dict) -> httpx.Response:
        return self.request("POST", path, json=json)

    def request(self, method: str, path: str, params: dict | None = None, json: dict | None = None) -> httpx.Response:
        @retry(
            retry=retry_if_exception_type(RetryableHTTPError),
            stop=stop_after_attempt(self.max_attempts),
            wait=_WaitRespectingRetryAfter(wait_exponential(multiplier=self.backoff_initial, max=30) + wait_random(0, self.backoff_initial)),
            reraise=True,
        )
        def _once() -> httpx.Response:
            self.attempts_made += 1
            self.limiter.wait()
            try:
                resp = self.client.request(method, path, params=params, json=json)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                raise RetryableHTTPError(f"network error: {e!r}") from e
            if resp.status_code == 429 or resp.status_code >= 500:
                ra = resp.headers.get("Retry-After")
                raise RetryableHTTPError(f"HTTP {resp.status_code}", float(ra) if ra and ra.isdigit() else None)
            return resp

        return _once()
