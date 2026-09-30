"""Unit tests for the Supabase storage layer against an in-memory fake
PostgREST server (no network required)."""

import json

import httpx

from rag.auth import AuthError, AuthService, ConflictError
from rag.supabase_auth import SupabaseStorage


class _FakePostgREST:
    def __init__(self):
        self.users = []
        self.otps = []
        self.sessions = []
        self.next_id = 1

    @staticmethod
    def _match(row, params) -> bool:
        for key, value in params.items():
            if key in ("select", "order", "limit"):
                continue
            if value.startswith("eq."):
                val = value[3:]
                try:
                    val = int(val)
                except ValueError:
                    pass
                if row.get(key) != val:
                    return False
            elif value.startswith("gt."):
                if not (float(row[key]) > float(value[3:])):
                    return False
        return True

    def _apply(self, request, rows):
        params = request.url.params
        rows = [r for r in rows if self._match(r, params)]
        if params.get("order", "") == "id.desc":
            rows = sorted(rows, key=lambda r: r.get("id", 0), reverse=True)
        if params.get("limit"):
            rows = rows[: int(params["limit"])]
        return rows

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        body = json.loads(request.content) if request.content else {}

        if path.endswith("auth_users"):
            if method == "GET":
                return httpx.Response(200, json=self._apply(request, self.users))
            if method == "POST":
                data = body
                if any(u["email"] == data["email"] for u in self.users):
                    return httpx.Response(409, json={"code": "23505"})
                row = {"id": self.next_id, **data}
                self.next_id += 1
                self.users.append(row)
                return httpx.Response(201, json=[row])
            if method == "PATCH":
                data = body
                for u in self._apply(request, self.users):
                    u.update(data)
                return httpx.Response(200, json=[])

        if path.endswith("auth_otp_codes"):
            if method == "GET":
                return httpx.Response(200, json=self._apply(request, self.otps))
            if method == "POST":
                row = {"id": self.next_id, **body}
                self.next_id += 1
                self.otps.append(row)
                return httpx.Response(201, json=[row])
            if method == "PATCH":
                data = body
                for o in self._apply(request, self.otps):
                    o.update(data)
                return httpx.Response(200, json=[])
            if method == "DELETE":
                self.otps = [o for o in self.otps if not self._match(o, request.url.params)]
                return httpx.Response(200, json=[])

        if path.endswith("auth_sessions"):
            if method == "GET":
                return httpx.Response(200, json=self._apply(request, self.sessions))
            if method == "POST":
                row = body
                self.sessions.append(row)
                return httpx.Response(201, json=[row])
            if method == "DELETE":
                self.sessions = [s for s in self.sessions if not self._match(s, request.url.params)]
                return httpx.Response(200, json=[])

        return httpx.Response(404, json={})


def _service():
    fake = _FakePostgREST()
    client = httpx.Client(transport=httpx.MockTransport(fake.handler))
    storage = SupabaseStorage("https://fake.supabase.co", "anon", "service", client=client)
    return AuthService(storage), fake


def test_signup_verify_login_session_flow():
    service, fake = _service()
    user = service.create_user("Jane Cooper", "jane@example.com", "StrongPass1!")
    assert user["id"] == 1
    assert fake.users[0]["password_hash"].startswith("")

    # Duplicate email conflicts
    try:
        service.create_user("Other", "jane@example.com", "AnotherPass1!")
        assert False, "expected ConflictError path -> AuthError 409"
    except AuthError as exc:
        assert exc.status == 409

    otp = service.request_otp("jane@example.com", "signup")
    assert len(otp["code"]) == 6 and otp["code"].isdigit()

    service.verify_otp("jane@example.com", otp["code"], "signup")
    service.mark_verified("jane@example.com")
    assert service.get_user_by_email("jane@example.com")["verified"] is True

    # Password login works after verification
    assert service.check_login("jane@example.com", "StrongPass1!")["id"] == 1
    try:
        service.check_login("jane@example.com", "bad-password")
        assert False, "expected 401"
    except AuthError as exc:
        assert exc.status == 401

    token = service.create_session(1)
    assert service.get_user_by_session(token)["email"] == "jane@example.com"
    service.delete_session(token)
    assert service.get_user_by_session(token) is None


def test_otp_three_wrong_attempts_lock():
    service, _ = _service()
    service.create_user("Lock Test", "lock@example.com", "StrongPass1!")
    otp = service.request_otp("lock@example.com", "signup")

    for _ in range(2):
        try:
            service.verify_otp("lock@example.com", "000000", "signup")
            assert False, "expected wrong-code error"
        except AuthError as exc:
            assert exc.status == 400
            assert exc.details.get("attempts_left")

    try:
        service.verify_otp("lock@example.com", "000000", "signup")
        assert False, "expected invalidation"
    except AuthError as exc:
        assert exc.status == 429
        assert "new verification code" in exc.message

    # The OTP is invalidated after the third wrong attempt, even if the old code is later supplied.
    try:
        service.verify_otp("lock@example.com", otp["code"], "signup")
        assert False, "expected invalidated OTP to be rejected"
    except AuthError as exc:
        assert exc.status == 400


def test_expired_code_rejected():
    service, fake = _service()
    service.create_user("Exp", "exp@example.com", "StrongPass1!")
    otp = service.request_otp("exp@example.com", "signup")
    # Force expiry
    fake.otps[0]["expires_at"] = 0
    try:
        service.verify_otp("exp@example.com", otp["code"], "signup")
        assert False, "expected expired error"
    except AuthError as exc:
        assert exc.status == 410

