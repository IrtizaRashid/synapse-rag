import time
from pathlib import Path

import pytest

from rag.auth import AuthError, AuthService, LocalStorage


def service(tmp_path: Path):
    return AuthService(LocalStorage(tmp_path / "auth.db"))


def create_verified_user(svc: AuthService, email="reset@example.com", password="StrongPass1!"):
    user = svc.create_user("Reset User", email, password)
    svc.mark_verified(email)
    return user


def test_password_reset_happy_path_revokes_sessions(tmp_path):
    svc = service(tmp_path)
    user = create_verified_user(svc)
    session = svc.create_session(user["id"])
    otp = svc.request_otp("reset@example.com", "reset")
    svc.verify_otp("reset@example.com", otp["code"], "reset")
    token = svc.create_reset_challenge("reset@example.com")

    svc.reset_password(token, "NewStrongPass1!")

    with pytest.raises(AuthError):
        svc.check_login("reset@example.com", "StrongPass1!")
    assert svc.check_login("reset@example.com", "NewStrongPass1!")["email"] == "reset@example.com"
    assert svc.get_user_by_session(session) is None


def test_reset_otp_expires_and_is_deleted(tmp_path):
    svc = service(tmp_path)
    create_verified_user(svc)
    otp = svc.request_otp("reset@example.com", "reset")
    svc._s.set_otp_attempts(1, 0)  # keep row touched for sqlite commit path
    with svc._s._lock:
        svc._s._conn.execute("UPDATE otp_codes SET expires_at=? WHERE email=? AND purpose=?", (time.time() - 1, "reset@example.com", "reset"))
        svc._s._conn.commit()
    with pytest.raises(AuthError) as err:
        svc.verify_otp("reset@example.com", otp["code"], "reset")
    assert err.value.status == 410
    with pytest.raises(AuthError):
        svc.verify_otp("reset@example.com", otp["code"], "reset")


def test_reset_otp_invalidated_after_three_wrong_attempts(tmp_path):
    svc = service(tmp_path)
    create_verified_user(svc)
    otp = svc.request_otp("reset@example.com", "reset")
    for _ in range(2):
        with pytest.raises(AuthError) as err:
            svc.verify_otp("reset@example.com", "000000", "reset")
        assert err.value.status == 400
    with pytest.raises(AuthError) as err:
        svc.verify_otp("reset@example.com", "000000", "reset")
    assert err.value.status == 429
    with pytest.raises(AuthError):
        svc.verify_otp("reset@example.com", otp["code"], "reset")


def test_reset_token_cannot_be_reused(tmp_path):
    svc = service(tmp_path)
    create_verified_user(svc)
    otp = svc.request_otp("reset@example.com", "reset")
    svc.verify_otp("reset@example.com", otp["code"], "reset")
    token = svc.create_reset_challenge("reset@example.com")
    svc.reset_password(token, "NewStrongPass1!")
    with pytest.raises(AuthError):
        svc.reset_password(token, "AnotherStrongPass1!")


def test_reset_request_does_not_reveal_missing_email(tmp_path):
    svc = service(tmp_path)
    result = svc.request_otp("missing@example.com", "reset")
    assert result["skipped"] is True
    assert result["code"] is None
