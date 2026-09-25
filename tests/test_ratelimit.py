"""The in-memory sliding-window rate limiter hosted mode puts on every request."""

from altarmy_profit.ratelimit import RateLimiter, client_ip


def test_allows_up_to_the_limit_per_window_and_key() -> None:
    now = [100.0]
    limiter = RateLimiter(3, 60, clock=lambda: now[0])
    assert [limiter.hit("a") for _ in range(3)] == [None, None, None]
    retry = limiter.hit("a")
    assert retry is not None and 0 < retry <= 60
    assert limiter.hit("b") is None  # every key has its own window
    now[0] += 30
    assert limiter.hit("a") is not None  # rejected hits don't count, but the window hasn't moved
    now[0] += 31
    assert limiter.hit("a") is None


def test_forgets_idle_keys() -> None:
    now = [0.0]
    limiter = RateLimiter(1, 10, clock=lambda: now[0])
    for i in range(50):
        limiter.hit(str(i))
    now[0] += 11
    limiter.sweep()
    assert len(limiter) == 0


def test_client_ip_prefers_the_forwarded_client() -> None:
    assert client_ip({"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, "10.0.0.2") == "203.0.113.9"
    assert client_ip({"x-forwarded-for": " 203.0.113.9 "}, None) == "203.0.113.9"
    assert client_ip({}, "10.0.0.2") == "10.0.0.2"
    assert client_ip({}, None) == "unknown"
