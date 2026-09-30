"""Security hardening: response headers, rate limiting, login lockout and
CSRF origin validation. Everything is lightweight, in-memory and dependency-free.

Tunables (env):
  RATE_LIMIT_ENABLED     (default "true"; set "false" to disable for tests)
  AUTH_RATE_LIMIT        (default 10)  requests / minute / IP on auth endpoints
  ASK_RATE_LIMIT         (default 20)  requests / minute / IP on /api/ask
  LOGIN_MAX_FAILURES     (default 5)   failed logins before temporary lock
  LOGIN_LOCK_SECONDS     (default 900) lock duration after too many failures
  ALLOWED_ORIGINS        comma-separated extra origins allowed (e.g. https://rag.example.com)
"""

from __future__ import annotations

import os
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import HTTPException, Request

RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() != "false"
AUTH_RATE_LIMIT = int(os.getenv("AUTH_RATE_LIMIT", "10"))
ASK_RATE_LIMIT = int(os.getenv("ASK_RATE_LIMIT", "20"))
INGEST_RATE_LIMIT = int(os.getenv("INGEST_RATE_LIMIT", "10"))
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCK_SECONDS = int(os.getenv("LOGIN_LOCK_SECONDS", "900"))
ALLOWED_ORIGINS = {o.strip().lower() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()}

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}

log = logging.getLogger("rag.request")


def client_ip(request: Request) -> str:
    """Return the client IP, honoring a trusted proxy header when enabled."""
    if os.getenv("TRUST_PROXY", "false").strip().lower() == "true":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return (request.client.host if request.client else "unknown")


def verify_csrf(request: Request) -> None:
    """Block cross-site state-changing requests from browsers.

    Requests without an Origin/Referer (curl, n8n, scripts) are allowed; only
    mismatched origins are rejected. Combined with SameSite=Lax cookies this
    neutralises browser-based CSRF.
    """
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return
    origin = (request.headers.get("origin") or request.headers.get("referer") or "").strip()
    if not origin:
        return
    host = (request.headers.get("host") or "").strip().lower()
    try:
        parsed = urlparse(origin)
        origin_host = parsed.netloc.lower()
        if not origin_host:
            raise ValueError("no netloc")
    except Exception:
        raise HTTPException(status_code=403, detail="Cross-site request blocked.") from None
    allowed = {o.strip().lower() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()}
    allowed_hosts = set()
    for entry in allowed:
        try:
            allowed_hosts.add(urlparse(entry).netloc.lower() or entry)
        except Exception:
            allowed_hosts.add(entry)
    if origin_host == host or origin_host in allowed_hosts:
        return
    raise HTTPException(status_code=403, detail="Cross-site request blocked.")


class RateLimiter:
    """Sliding-window rate limiter keyed by path + client IP."""

    def __init__(self, calls: int, period: int = 60):
        self.calls = calls
        self.period = period
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            window = self._hits[key]
            while window and window[0] < now - self.period:
                window.popleft()
            if len(window) >= self.calls:
                return False
            window.append(now)
            return True

    def dependency(self, request: Request) -> None:
        if not RATE_LIMIT_ENABLED:
            return
        key = f"{request.url.path}|{client_ip(request)}"
        if not self.allow(key):
            raise HTTPException(status_code=429, detail="Too many requests. Please slow down and try again.")


class LoginLockout:
    """Locks an email+IP after too many failed password logins."""

    def __init__(self, max_failures: int = LOGIN_MAX_FAILURES, lock_seconds: int = LOGIN_LOCK_SECONDS):
        self.max_failures = max_failures
        self.lock_seconds = lock_seconds
        self._fails: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def _key(self, email: str, ip: str) -> str:
        return f"{email.strip().lower()}|{ip}"

    def is_locked(self, email: str, ip: str) -> bool:
        with self._lock:
            count, until = self._fails.get(self._key(email, ip), (0, 0.0))
            return count >= self.max_failures and until > time.time()

    def record_failure(self, email: str, ip: str) -> int:
        key = self._key(email, ip)
        with self._lock:
            count, until = self._fails.get(key, (0, 0.0))
            count += 1
            if count >= self.max_failures:
                until = time.time() + self.lock_seconds
            self._fails[key] = (count, until)
            return count

    def reset(self, email: str, ip: str) -> None:
        with self._lock:
            self._fails.pop(self._key(email, ip), None)


class SecurityHeadersMiddleware:
    """Pure ASGI middleware adding security headers to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                for name, value in SECURITY_HEADERS.items():
                    headers.append((name.lower().encode(), value.encode()))
                content_type = b""
                for key, value in headers:
                    if key == b"content-type":
                        content_type = value
                        break
                if content_type.startswith(b"text/html"):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RequestLoggingMiddleware:
    """Add request IDs and lightweight access logs to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        method = scope.get("method", "")
        path = scope.get("path", "")
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log.info(
                "request completed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status": status_code,
                    "duration_ms": duration_ms,
                },
            )


auth_rate_limiter = RateLimiter(AUTH_RATE_LIMIT)
ask_rate_limiter = RateLimiter(ASK_RATE_LIMIT)
ingest_rate_limiter = RateLimiter(INGEST_RATE_LIMIT)
login_lockout = LoginLockout()
