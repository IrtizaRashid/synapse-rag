"""Authentication core with pluggable storage.

Business logic (passwords, OTP lifecycle, 3-attempt lockout, sessions) lives
in `AuthService` and is storage-agnostic. Two storages are provided:
  - LocalStorage   (SQLite, default, zero-config)
  - SupabaseStorage(Postgres via Supabase REST, rag/supabase_auth.py)

`store` at the bottom is the configured service (AUTH_BACKEND env var).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path

try:  # load project .env regardless of import order (see app.py)
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass

OTP_LENGTH = int(os.getenv("OTP_LENGTH", "6"))
OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "180"))          # 3 min
MAX_OTP_ATTEMPTS = int(os.getenv("MAX_OTP_ATTEMPTS", "3"))
OTP_LOCK_SECONDS = int(os.getenv("OTP_LOCK_SECONDS", "0"))          # invalidate after max attempts
OTP_RESEND_COOLDOWN = int(os.getenv("OTP_RESEND_COOLDOWN", "60"))   # 60 s
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))
RESET_TOKEN_TTL_SECONDS = int(os.getenv("RESET_TOKEN_TTL_SECONDS", "600"))
PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "12"))
DB_PATH = Path(os.getenv("AUTH_DB_PATH", str(Path(__file__).resolve().parent / "data" / "auth.db")))

log = logging.getLogger("auth")


class AuthError(Exception):
    """User-facing auth failure. `details` may carry extra data."""

    def __init__(self, message: str, *, details: dict | None = None, status: int = 400):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.status = status


class ConflictError(Exception):
    """Raised by storage when a unique constraint (email) is violated."""


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return hmac.compare_digest(digest.hex(), expected)


def _hash_code(code: str) -> str:
    pepper = os.getenv("OTP_PEPPER", os.getenv("AUTH_SECRET", "synapse-local-dev-pepper"))
    return hmac.new(pepper.encode(), code.encode(), hashlib.sha256).hexdigest()


def _hash_token(token: str) -> str:
    pepper = os.getenv("RESET_TOKEN_PEPPER", os.getenv("AUTH_SECRET", "synapse-local-dev-token-pepper"))
    return hmac.new(pepper.encode(), token.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Storage interface
# ---------------------------------------------------------------------------
class AuthStorage(ABC):
    @abstractmethod
    def get_user_by_email(self, email: str) -> dict | None: ...

    @abstractmethod
    def get_user_by_id(self, user_id: int) -> dict | None: ...

    @abstractmethod
    def insert_user(self, name: str, email: str, password_hash: str, created_at: float) -> dict: ...

    @abstractmethod
    def set_verified(self, email: str, value: bool) -> None: ...

    @abstractmethod
    def get_latest_otp(self, email: str, purpose: str) -> dict | None: ...

    @abstractmethod
    def insert_otp(self, email: str, purpose: str, code_hash: str, created_at: float, expires_at: float) -> int: ...

    @abstractmethod
    def set_otp_attempts(self, otp_id: int, attempts: int) -> None: ...

    @abstractmethod
    def set_otp_lock(self, otp_id: int, attempts: int, lock_until: float) -> None: ...

    @abstractmethod
    def delete_otps(self, email: str, purpose: str) -> None: ...

    @abstractmethod
    def insert_session(self, token: str, user_id: int, expires_at: float) -> None: ...

    @abstractmethod
    def get_user_by_session(self, token: str) -> dict | None: ...

    @abstractmethod
    def delete_session(self, token: str) -> None: ...

    @abstractmethod
    def delete_sessions_for_user(self, user_id: int) -> None: ...

    @abstractmethod
    def update_password(self, user_id: int, password_hash: str) -> None: ...

    @abstractmethod
    def insert_reset_challenge(self, email: str, token_hash: str, created_at: float, expires_at: float) -> None: ...

    @abstractmethod
    def get_reset_challenge(self, token_hash: str) -> dict | None: ...

    @abstractmethod
    def delete_reset_challenge(self, token_hash: str) -> None: ...

    @abstractmethod
    def delete_reset_challenges_for_email(self, email: str) -> None: ...


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------
class AuthService:
    def __init__(self, storage: AuthStorage):
        self._s = storage

    def create_user(self, name: str, email: str, password: str) -> dict:
        email = email.strip().lower()
        self._validate_password(password)
        if len(name.strip()) < 2:
            raise AuthError("Please enter your full name.")
        if self._s.get_user_by_email(email):
            raise AuthError("An account with this email already exists. Please sign in.", status=409)
        try:
            return self._s.insert_user(name.strip(), email, _hash_password(password), time.time())
        except ConflictError:
            raise AuthError("An account with this email already exists. Please sign in.", status=409) from None

    def _validate_password(self, password: str) -> None:
        if len(password) < PASSWORD_MIN_LENGTH:
            raise AuthError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
        if not any(ch.islower() for ch in password) or not any(ch.isupper() for ch in password) or not any(ch.isdigit() for ch in password):
            raise AuthError("Password must include uppercase, lowercase, and a number.")

    def get_user_by_email(self, email: str) -> dict | None:
        return self._s.get_user_by_email(email.strip().lower())

    def get_user_by_id(self, user_id: int) -> dict | None:
        return self._s.get_user_by_id(user_id)

    def check_login(self, email: str, password: str) -> dict:
        user = self.get_user_by_email(email)
        if not user or not _verify_password(password, user["password_hash"]):
            raise AuthError("Invalid email or password.", status=401)
        return user

    def mark_verified(self, email: str) -> None:
        self._s.set_verified(email.strip().lower(), True)

    def oauth_user(self, name: str, email: str, email_verified: bool = True) -> dict:
        email = email.strip().lower()
        user = self.get_user_by_email(email)
        if user:
            if email_verified and not user.get("verified"):
                self.mark_verified(email)
                user = self.get_user_by_email(email) or user
            return user
        if not email_verified:
            raise AuthError("Google did not verify this email address.", status=403)
        password_hash = _hash_password(secrets.token_urlsafe(48))
        try:
            user = self._s.insert_user(name.strip() or email.split("@")[0], email, password_hash, time.time())
        except ConflictError:
            user = self.get_user_by_email(email)
            if not user:
                raise
        self.mark_verified(email)
        return self.get_user_by_email(email) or user

    def request_otp(self, email: str, purpose: str) -> dict:
        email = email.strip().lower()
        user = self.get_user_by_email(email)
        if purpose == "signup" and user and user["verified"]:
            raise AuthError("Account already verified. Please sign in.")
        if purpose == "signup" and not user:
            raise AuthError("No account found for this email. Please sign up first.")
        if purpose == "login" and not user:
            raise AuthError("No account found for this email. Please sign up first.")
        if purpose == "reset" and not user:
            # Do not reveal whether an email exists for password recovery.
            return {"code": None, "skipped": True}

        now = time.time()
        row = self._s.get_latest_otp(email, purpose)
        if row:
            if row["lock_until"] > now:
                raise AuthError("Too many attempts. Please wait.", status=429)
            if now - row["created_at"] < OTP_RESEND_COOLDOWN:
                wait = int(OTP_RESEND_COOLDOWN - (now - row["created_at"]))
                raise AuthError("Please wait before resending.", status=429, details={"wait": wait})

        code = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
        self._s.delete_otps(email, purpose)
        self._s.insert_otp(email, purpose, _hash_code(code), now, now + OTP_TTL_SECONDS)
        return {"code": code, "skipped": False}

    def verify_otp(self, email: str, code: str, purpose: str) -> dict:
        email = email.strip().lower()
        code = code.strip()
        now = time.time()
        row = self._s.get_latest_otp(email, purpose)
        if not row:
            raise AuthError("No verification requested for this email.", status=400)

        if row["lock_until"] > now:
            raise AuthError(
                "Too many incorrect attempts. Your verification is locked.",
                status=429,
                details={"lock_seconds": int(row["lock_until"] - now)},
            )
        if row["expires_at"] < now:
            self._s.delete_otps(email, purpose)
            raise AuthError("This verification code has expired. Request a new code.", status=410)

        if not hmac.compare_digest(_hash_code(code), row["code_hash"]):
            attempts = int(row["attempts"]) + 1
            remaining = MAX_OTP_ATTEMPTS - attempts
            if remaining <= 0:
                self._s.delete_otps(email, purpose)
                raise AuthError(
                    "Too many incorrect attempts. Request a new verification code.",
                    status=429,
                    details={"lock_seconds": OTP_LOCK_SECONDS},
                )
            self._s.set_otp_attempts(int(row["id"]), attempts)
            raise AuthError(
                f"Incorrect code. {remaining} attempt(s) remaining.",
                status=400,
                details={"attempts_left": remaining},
            )

        self._s.delete_otps(email, purpose)
        return {"ok": True}

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        self._s.insert_session(token, user_id, time.time() + SESSION_TTL_DAYS * 86400)
        return token

    def get_user_by_session(self, token: str) -> dict | None:
        if not token:
            return None
        return self._s.get_user_by_session(token)

    def delete_session(self, token: str) -> None:
        if token:
            self._s.delete_session(token)

    def delete_sessions_for_user(self, user_id: int) -> None:
        self._s.delete_sessions_for_user(user_id)

    def create_reset_challenge(self, email: str) -> str:
        email = email.strip().lower()
        self._s.delete_reset_challenges_for_email(email)
        token = secrets.token_urlsafe(32)
        now = time.time()
        self._s.insert_reset_challenge(email, _hash_token(token), now, now + RESET_TOKEN_TTL_SECONDS)
        return token

    def reset_password(self, token: str, new_password: str) -> dict:
        self._validate_password(new_password)
        token_hash = _hash_token(token.strip())
        challenge = self._s.get_reset_challenge(token_hash)
        if not challenge or float(challenge["expires_at"]) < time.time():
            if challenge:
                self._s.delete_reset_challenge(token_hash)
            raise AuthError("Password reset session expired. Request a new code.", status=410)
        user = self.get_user_by_email(challenge["email"])
        if not user:
            self._s.delete_reset_challenge(token_hash)
            raise AuthError("Password reset session expired. Request a new code.", status=410)
        self._s.update_password(int(user["id"]), _hash_password(new_password))
        self._s.delete_reset_challenge(token_hash)
        self._s.delete_otps(user["email"], "reset")
        self._s.delete_sessions_for_user(int(user["id"]))
        return {"ok": True}


# ---------------------------------------------------------------------------
# Local storage (SQLite)
# ---------------------------------------------------------------------------
class LocalStorage(AuthStorage):
    def __init__(self, path: Path = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS otp_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lock_until REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS password_reset_challenges (
                    token_hash TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_reset_challenges_email ON password_reset_challenges(email);
                CREATE INDEX IF NOT EXISTS idx_otp_email ON otp_codes(email, purpose);
                """
            )
            self._conn.commit()

    def _row(self, row) -> dict | None:
        return dict(row) if row else None

    def _validate_password(self, password: str) -> None:
        if len(password) < PASSWORD_MIN_LENGTH:
            raise AuthError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
        if not any(ch.islower() for ch in password) or not any(ch.isupper() for ch in password) or not any(ch.isdigit() for ch in password):
            raise AuthError("Password must include uppercase, lowercase, and a number.")

    def get_user_by_email(self, email: str) -> dict | None:
        with self._lock:
            return self._row(self._conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone())

    def get_user_by_id(self, user_id: int) -> dict | None:
        with self._lock:
            return self._row(self._conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def insert_user(self, name: str, email: str, password_hash: str, created_at: float) -> dict:
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO users (name, email, password_hash, verified, created_at) VALUES (?,?,?,0,?)",
                    (name, email, password_hash, created_at),
                )
                self._conn.commit()
                return {"id": cur.lastrowid, "name": name, "email": email, "password_hash": password_hash,
                        "verified": 0, "created_at": created_at}
            except sqlite3.IntegrityError:
                raise ConflictError from None

    def set_verified(self, email: str, value: bool) -> None:
        with self._lock:
            self._conn.execute("UPDATE users SET verified=? WHERE email=?", (1 if value else 0, email))
            self._conn.commit()

    def get_latest_otp(self, email: str, purpose: str) -> dict | None:
        with self._lock:
            return self._row(self._conn.execute(
                "SELECT * FROM otp_codes WHERE email=? AND purpose=? ORDER BY id DESC LIMIT 1", (email, purpose)
            ).fetchone())

    def insert_otp(self, email: str, purpose: str, code_hash: str, created_at: float, expires_at: float) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO otp_codes (email, purpose, code_hash, created_at, expires_at) VALUES (?,?,?,?,?)",
                (email, purpose, code_hash, created_at, expires_at),
            )
            self._conn.commit()
            return cur.lastrowid

    def set_otp_attempts(self, otp_id: int, attempts: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE otp_codes SET attempts=? WHERE id=?", (attempts, otp_id))
            self._conn.commit()

    def set_otp_lock(self, otp_id: int, attempts: int, lock_until: float) -> None:
        with self._lock:
            self._conn.execute("UPDATE otp_codes SET attempts=?, lock_until=? WHERE id=?", (attempts, lock_until, otp_id))
            self._conn.commit()

    def delete_otps(self, email: str, purpose: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM otp_codes WHERE email=? AND purpose=?", (email, purpose))
            self._conn.commit()

    def insert_session(self, token: str, user_id: int, expires_at: float) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                               (token, user_id, time.time(), expires_at))
            self._conn.commit()

    def get_user_by_session(self, token: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at>?",
                (token, time.time()),
            ).fetchone()
        return self._row(row)

    def delete_session(self, token: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            self._conn.commit()

    def delete_sessions_for_user(self, user_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self._conn.commit()

    def update_password(self, user_id: int, password_hash: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))
            self._conn.commit()

    def insert_reset_challenge(self, email: str, token_hash: str, created_at: float, expires_at: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO password_reset_challenges(token_hash,email,created_at,expires_at) VALUES (?,?,?,?)",
                (token_hash, email, created_at, expires_at),
            )
            self._conn.commit()

    def get_reset_challenge(self, token_hash: str) -> dict | None:
        with self._lock:
            return self._row(self._conn.execute(
                "SELECT * FROM password_reset_challenges WHERE token_hash=?", (token_hash,)
            ).fetchone())

    def delete_reset_challenge(self, token_hash: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM password_reset_challenges WHERE token_hash=?", (token_hash,))
            self._conn.commit()

    def delete_reset_challenges_for_email(self, email: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM password_reset_challenges WHERE email=?", (email,))
            self._conn.commit()


def public_user(user: dict) -> dict:
    return {"id": user["id"], "name": user["name"], "email": user["email"], "verified": bool(user["verified"])}


def _build_service() -> AuthService:
    if os.getenv("AUTH_BACKEND", "local").strip().lower() == "supabase":
        from rag.supabase_auth import SupabaseStorage

        url = os.getenv("SUPABASE_URL", "").strip()
        anon = os.getenv("SUPABASE_ANON_KEY", "").strip()
        service = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not (url and anon and service):
            raise RuntimeError("AUTH_BACKEND=supabase requires SUPABASE_URL, SUPABASE_ANON_KEY and SUPABASE_SERVICE_ROLE_KEY")
        log.info("Auth backend: Supabase (%s)", url)
        return AuthService(SupabaseStorage(url, anon, service))
    log.info("Auth backend: local SQLite (%s)", DB_PATH)
    return AuthService(LocalStorage(DB_PATH))


store = _build_service()
