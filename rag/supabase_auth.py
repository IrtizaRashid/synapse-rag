"""Supabase (Postgres) storage for the auth service.

Uses Supabase's PostgREST REST API directly through httpx (already a project
dependency) with the anon key for the client and the service-role key for
privileged row access. Requires the tables created by `supabase/schema.sql`.

Tables:
  - auth_users      (id, name, email, password_hash, verified, created_at)
  - auth_otp_codes  (id, email, purpose, code_hash, created_at, expires_at, attempts, lock_until)
  - auth_sessions   (token, user_id, created_at, expires_at)
  - auth_password_reset_challenges (token_hash, email, created_at, expires_at)
"""

from __future__ import annotations

import logging

import httpx

from .auth import AuthStorage, ConflictError

log = logging.getLogger("auth.supabase")


class SupabaseStorage(AuthStorage):
    def __init__(self, url: str, anon_key: str, service_role_key: str, client: httpx.Client | None = None):
        self.base = url.rstrip("/")
        self._anon = anon_key
        self._service = service_role_key
        self._client = client or httpx.Client(timeout=20)

    # ------------------------------------------------------------------ util
    def _headers(self) -> dict:
        return {
            "apikey": self._anon,
            "Authorization": f"Bearer {self._service}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _url(self, table: str) -> str:
        return f"{self.base}/rest/v1/{table}"

    def _rows(self, response: httpx.Response) -> list[dict]:
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else [data]

    def _first(self, response: httpx.Response) -> dict | None:
        rows = self._rows(response)
        return rows[0] if rows else None

    # ----------------------------------------------------------------- users
    def get_user_by_email(self, email: str) -> dict | None:
        r = self._client.get(self._url("auth_users"), params={"email": f"eq.{email}", "select": "*"}, headers=self._headers())
        return self._first(r)

    def get_user_by_id(self, user_id: int) -> dict | None:
        r = self._client.get(self._url("auth_users"), params={"id": f"eq.{user_id}", "select": "*"}, headers=self._headers())
        return self._first(r)

    def insert_user(self, name: str, email: str, password_hash: str, created_at: float) -> dict:
        r = self._client.post(
            self._url("auth_users"),
            json={"name": name, "email": email, "password_hash": password_hash,
                  "verified": False, "created_at": created_at},
            headers=self._headers(),
        )
        if r.status_code == 409:
            raise ConflictError
        user = self._first(r)
        if user is None:
            raise RuntimeError(f"Supabase insert_user returned no row: {r.status_code} {r.text}")
        return user

    def set_verified(self, email: str, value: bool) -> None:
        self._client.patch(
            self._url("auth_users"), params={"email": f"eq.{email}"}, json={"verified": value}, headers=self._headers()
        ).raise_for_status()

    # ------------------------------------------------------------------- otp
    def get_latest_otp(self, email: str, purpose: str) -> dict | None:
        r = self._client.get(
            self._url("auth_otp_codes"),
            params={"email": f"eq.{email}", "purpose": f"eq.{purpose}", "select": "*",
                    "order": "id.desc", "limit": "1"},
            headers=self._headers(),
        )
        return self._first(r)

    def insert_otp(self, email: str, purpose: str, code_hash: str, created_at: float, expires_at: float) -> int:
        r = self._client.post(
            self._url("auth_otp_codes"),
            json={"email": email, "purpose": purpose, "code_hash": code_hash,
                  "created_at": created_at, "expires_at": expires_at, "attempts": 0, "lock_until": 0},
            headers=self._headers(),
        )
        row = self._first(r)
        if row is None:
            raise RuntimeError(f"Supabase insert_otp returned no row: {r.status_code} {r.text}")
        return int(row["id"])

    def set_otp_attempts(self, otp_id: int, attempts: int) -> None:
        self._client.patch(
            self._url("auth_otp_codes"), params={"id": f"eq.{otp_id}"}, json={"attempts": attempts}, headers=self._headers()
        ).raise_for_status()

    def set_otp_lock(self, otp_id: int, attempts: int, lock_until: float) -> None:
        self._client.patch(
            self._url("auth_otp_codes"),
            params={"id": f"eq.{otp_id}"},
            json={"attempts": attempts, "lock_until": lock_until},
            headers=self._headers(),
        ).raise_for_status()

    def delete_otps(self, email: str, purpose: str) -> None:
        self._client.delete(
            self._url("auth_otp_codes"), params={"email": f"eq.{email}", "purpose": f"eq.{purpose}"}, headers=self._headers()
        ).raise_for_status()

    # -------------------------------------------------------------- sessions
    def insert_session(self, token: str, user_id: int, expires_at: float) -> None:
        self._client.post(
            self._url("auth_sessions"),
            json={"token": token, "user_id": user_id, "created_at": time_now(), "expires_at": expires_at},
            headers=self._headers(),
        ).raise_for_status()

    def get_user_by_session(self, token: str) -> dict | None:
        r = self._client.get(
            self._url("auth_sessions"),
            params={"token": f"eq.{token}", "expires_at": f"gt.{time_now()}", "select": "user_id", "limit": "1"},
            headers=self._headers(),
        )
        row = self._first(r)
        if not row:
            return None
        return self.get_user_by_id(int(row["user_id"]))

    def delete_session(self, token: str) -> None:
        self._client.delete(self._url("auth_sessions"), params={"token": f"eq.{token}"}, headers=self._headers()).raise_for_status()

    def delete_sessions_for_user(self, user_id: int) -> None:
        self._client.delete(
            self._url("auth_sessions"), params={"user_id": f"eq.{user_id}"}, headers=self._headers()
        ).raise_for_status()

    def update_password(self, user_id: int, password_hash: str) -> None:
        self._client.patch(
            self._url("auth_users"),
            params={"id": f"eq.{user_id}"},
            json={"password_hash": password_hash},
            headers=self._headers(),
        ).raise_for_status()

    def insert_reset_challenge(self, email: str, token_hash: str, created_at: float, expires_at: float) -> None:
        self._client.post(
            self._url("auth_password_reset_challenges"),
            json={"email": email, "token_hash": token_hash, "created_at": created_at, "expires_at": expires_at},
            headers=self._headers(),
        ).raise_for_status()

    def get_reset_challenge(self, token_hash: str) -> dict | None:
        r = self._client.get(
            self._url("auth_password_reset_challenges"),
            params={"token_hash": f"eq.{token_hash}", "select": "*", "limit": "1"},
            headers=self._headers(),
        )
        return self._first(r)

    def delete_reset_challenge(self, token_hash: str) -> None:
        self._client.delete(
            self._url("auth_password_reset_challenges"),
            params={"token_hash": f"eq.{token_hash}"},
            headers=self._headers(),
        ).raise_for_status()

    def delete_reset_challenges_for_email(self, email: str) -> None:
        self._client.delete(
            self._url("auth_password_reset_challenges"),
            params={"email": f"eq.{email}"},
            headers=self._headers(),
        ).raise_for_status()


def time_now() -> float:
    import time

    return time.time()
