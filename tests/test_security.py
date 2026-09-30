"""Unit tests for the security module."""

import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from rag.security import LoginLockout, RateLimiter, SecurityHeadersMiddleware, verify_csrf


class _FakeRequest:
    def __init__(self, method="POST", host="127.0.0.1:8000", origin=None, referer=None):
        self.method = method
        self.headers = {"host": host}
        if origin:
            self.headers["origin"] = origin
        if referer:
            self.headers["referer"] = referer


def test_rate_limiter_blocks_over_limit():
    limiter = RateLimiter(calls=3, period=60)
    for _ in range(3):
        assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    # different key unaffected
    assert limiter.allow("other") is True


def test_rate_limiter_resets_after_period():
    limiter = RateLimiter(calls=1, period=1)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    time.sleep(1.1)
    assert limiter.allow("k") is True


def test_login_lockout_after_max_failures():
    lock = LoginLockout(max_failures=3, lock_seconds=60)
    assert lock.is_locked("a@b.com", "1.2.3.4") is False
    lock.record_failure("a@b.com", "1.2.3.4")
    lock.record_failure("a@b.com", "1.2.3.4")
    lock.record_failure("a@b.com", "1.2.3.4")
    assert lock.is_locked("a@b.com", "1.2.3.4") is True
    # different IP not locked
    assert lock.is_locked("a@b.com", "9.9.9.9") is False
    lock.reset("a@b.com", "1.2.3.4")
    assert lock.is_locked("a@b.com", "1.2.3.4") is False


def test_csrf_missing_origin_allowed():
    verify_csrf(_FakeRequest())  # non-browser client, no origin -> allowed


def test_csrf_same_origin_allowed():
    verify_csrf(_FakeRequest(origin="http://127.0.0.1:8000"))
    verify_csrf(_FakeRequest(referer="http://127.0.0.1:8000/login"))


def test_csrf_cross_site_blocked():
    with pytest.raises(HTTPException) as exc:
        verify_csrf(_FakeRequest(origin="https://evil.example.com"))
    assert exc.value.status_code == 403


def test_security_headers_present():
    client = TestClient(SecurityHeadersMiddleware(_echo_app()))
    response = client.get("/")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


def test_security_headers_referrer_and_permissions():
    client = TestClient(SecurityHeadersMiddleware(_echo_app()))
    response = client.get("/")
    assert "strict-origin" in response.headers["referrer-policy"]
    assert "geolocation=()" in response.headers["permissions-policy"]


def test_security_headers_hsts_when_secure():
    import os
    old = os.environ.get("COOKIE_SECURE")
    os.environ["COOKIE_SECURE"] = "true"
    try:
        client = TestClient(SecurityHeadersMiddleware(_echo_app()))
        response = client.get("/")
        assert "max-age=" in response.headers.get("strict-transport-security", "")
    finally:
        if old is None:
            os.environ.pop("COOKIE_SECURE", None)
        else:
            os.environ["COOKIE_SECURE"] = old


def test_security_headers_html_not_cached_assets_allowed():
    client = TestClient(SecurityHeadersMiddleware(_echo_app()))
    html = client.get("/")
    assert html.headers["cache-control"] == "no-store"


def test_csrf_allowed_origins_env_respected():
    import os
    os.environ["ALLOWED_ORIGINS"] = "https://app.example.com"
    try:
        verify_csrf(_FakeRequest(origin="https://app.example.com"))
    finally:
        os.environ.pop("ALLOWED_ORIGINS", None)


def test_csrf_referer_cross_site_blocked():
    with pytest.raises(HTTPException) as exc:
        verify_csrf(_FakeRequest(referer="https://evil.example.com/phish"))
    assert exc.value.status_code == 403


def test_rate_limiter_sliding_window_counts_only_recent():
    limiter = RateLimiter(calls=2, period=5)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    time.sleep(1)
    # still within window -> still blocked
    assert limiter.allow("k") is False


def test_login_lockout_keyed_by_email_and_ip():
    lock = LoginLockout(max_failures=2, lock_seconds=60)
    lock.record_failure("a@b.com", "1.1.1.1")
    lock.record_failure("a@b.com", "1.1.1.1")
    assert lock.is_locked("a@b.com", "1.1.1.1") is True
    assert lock.is_locked("a@b.com", "2.2.2.2") is False
    assert lock.is_locked("c@d.com", "1.1.1.1") is False


def _echo_app():
    async def app(scope, receive, send):
        await receive()
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/html")],
        })
        await send({"type": "http.response.body", "body": b"<html></html>"})

    return app
