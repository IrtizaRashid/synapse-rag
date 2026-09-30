from __future__ import annotations

import logging
import os
import json
import secrets
from urllib.parse import urlencode

import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from rag.auth import AuthError, public_user, store as auth_store
from rag.chatbots import store as chatbot_store
from rag.email import send_otp_email
from rag.ingest import SUPPORTED, analyze_file, chunk_sections, extract_file, extract_url, ingest_directory
from rag.logging_config import configure_logging
from rag.llm import answer_with_sources, classify_intent, filter_relevant_results, rewrite_query
from rag.security import (
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    ask_rate_limiter,
    auth_rate_limiter,
    client_ip,
    ingest_rate_limiter,
    login_lockout,
    verify_csrf,
)
from rag.store import KnowledgeStore
from rag.workspace import store as workspace_store

log = logging.getLogger("rag.app")

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
load_dotenv(BASE / ".env")
configure_logging()
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
MAX_FILES_PER_USER = int(os.getenv("MAX_FILES_PER_USER", "200"))
MAX_STORAGE = int(os.getenv("MAX_STORAGE_MB", "1024")) * 1024 * 1024
SESSION_COOKIE = "rag_session"
RAG_BACKEND = os.getenv("RAG_BACKEND", "vector").strip().lower()
RAG_API_KEYS = [k.strip() for k in os.getenv("RAG_API_KEYS", "").split(",") if k.strip()]
INDEX_WORKERS = max(1, int(os.getenv("INDEX_WORKERS", "2")))
INDEX_INLINE = os.getenv("INDEX_INLINE", "false").lower() == "true"
INDEX_EXECUTOR = ThreadPoolExecutor(max_workers=INDEX_WORKERS, thread_name_prefix="rag-index")


def _cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "false").lower() == "true"


def _set_session_cookie(response: JSONResponse | RedirectResponse, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=86400 * int(os.getenv("SESSION_TTL_DAYS", "7")),
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
    )


def _safe_redirect_path(value: str | None, fallback: str = "/") -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return fallback
    return value


def _build_store():
    if RAG_BACKEND == "vector":
        url = os.getenv("SUPABASE_URL", "").strip()
        anon = os.getenv("SUPABASE_ANON_KEY", "").strip()
        service = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if url and anon and service and os.getenv("GEMINI_API_KEY", "").strip():
            from rag.embeddings import GeminiEmbedder
            from rag.vector_store import SupabaseVectorStore

            log.info("RAG backend: pgvector on Supabase")
            return SupabaseVectorStore(url, anon, service, GeminiEmbedder())
        log.warning("Vector backend requested but keys missing; falling back to TF-IDF.")
    data_path = os.getenv("RAG_DATA_PATH", str(BASE / "data" / "chunks.json"))
    log.info("RAG backend: local TF-IDF (%s)", data_path)
    return KnowledgeStore(data_path)


store = _build_store()

app = FastAPI(title="Multi-format OCR RAG", version="3.1.0")
app.mount("/assets", StaticFiles(directory=str(STATIC)), name="assets")

allowed_hosts = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
if allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)


# ---------------------------------------------------------------------------
# Session dependency
# ---------------------------------------------------------------------------
def require_session(session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = auth_store.get_user_by_session(session_token or "")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_api_or_session(request: Request, session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    """Accept a valid session cookie OR a trusted X-API-Key header.

    Enables headless clients (n8n, cron jobs, scripts) to use the RAG API
    without a browser session while browser users keep using their cookie.
    """
    api_key = request.headers.get("x-api-key", "").strip()
    if api_key and api_key in RAG_API_KEYS:
        return {"api": True}
    user = auth_store.get_user_by_session(session_token or "")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _html(name: str) -> HTMLResponse:
    return HTMLResponse((BASE / "static" / name).read_text(encoding="utf-8"))


def _frontend_redirect(request: Request, path: str = "") -> RedirectResponse | None:
    origin = os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")
    if not origin:
        return None
    # Starlette's TestClient follows external redirects back into the same ASGI
    # app, which turns a local dev convenience redirect into an infinite loop.
    if "testclient" in (request.headers.get("user-agent") or "").lower():
        return None
    return RedirectResponse(f"{origin}{path}")


# ---------------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------------
def _auth_guard(func):
    """Turn unexpected auth-backend failures into a clear 503."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as exc:
            log.exception("Auth endpoint failed")
            raise HTTPException(
                status_code=503,
                detail="Auth service is unavailable. If you just enabled Supabase, run "
                       "supabase/schema.sql in the Supabase SQL editor.",
            ) from exc

    return wrapper


class SignupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=1024)


class LoginRequest(BaseModel):
    email: str
    password: str | None = None


class OTPRequest(BaseModel):
    email: str
    purpose: str = Field(pattern="^(signup|login|reset)$")


class VerifyOTPRequest(BaseModel):
    email: str
    code: str = Field(min_length=4, max_length=8)
    purpose: str = Field(pattern="^(signup|login|reset)$")


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordVerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=8)


class ResetPasswordRequest(BaseModel):
    reset_token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=12, max_length=1024)


class URLRequest(BaseModel):
    url: str


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=int(os.getenv("TOP_K", "5")), ge=1, le=20)
    sources: list[str] | None = None
    chatbot_id: str | None = None


class DeleteRequest(BaseModel):
    source: str


class ChatbotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    sources: list[str] = Field(default_factory=list)
    avatar: str = Field(default="sparkles", max_length=40)
    instructions: str = Field(default="", max_length=4000)
    enabled: bool = True
    color: str = Field(default="#6d5dfc", max_length=20)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be empty")
        return value


class ChatbotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    sources: list[str] | None = None
    avatar: str | None = Field(default=None, max_length=40)
    instructions: str | None = Field(default=None, max_length=4000)
    enabled: bool | None = None
    color: str | None = Field(default=None, max_length=20)


class FileRename(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=120)
    bot_ids: list[str] = Field(default_factory=list)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    bot_ids: list[str] | None = None


class ConversationMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    bot_ids: list[str] | None = None
    attachments: list[str] = Field(default_factory=list)


def _owner_id(user: dict) -> int:
    try:
        return int(user.get("id", 0))
    except (TypeError, ValueError):
        return 0


def _owned_chatbots(user: dict) -> list[dict]:
    owner_id = _owner_id(user)
    rows = chatbot_store.list()
    if owner_id:
        rows = [row for row in rows if int(row.get("owner_id", 0)) == owner_id]
    output = []
    for row in rows:
        item = dict(row)
        item.update(workspace_store.get_bot_profile(owner_id, str(item["id"])))
        output.append(item)
    return output


@app.get("/api/auth/google/start")
def google_start(redirect: str = "/"):
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    app_url = os.getenv("APP_URL", os.getenv("BETTER_AUTH_URL", "http://127.0.0.1:8000")).rstrip("/")
    if not client_id or not os.getenv("GOOGLE_CLIENT_SECRET", "").strip():
        return RedirectResponse("/login?error=google_unavailable", status_code=302)
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "redirect_uri": f"{app_url}/api/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    response = RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}", status_code=302)
    response.set_cookie("google_oauth_state", state, max_age=600, httponly=True, samesite="lax", secure=_cookie_secure())
    response.set_cookie("post_auth_redirect", _safe_redirect_path(redirect), max_age=600, httponly=True, samesite="lax", secure=_cookie_secure())
    return response


@app.get("/api/auth/google/callback")
@_auth_guard
def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    google_oauth_state: str | None = Cookie(default=None),
    post_auth_redirect: str | None = Cookie(default="/"),
):
    if error or not code or not state or not google_oauth_state or not secrets.compare_digest(state, google_oauth_state):
        return RedirectResponse("/login?error=google_auth_failed", status_code=302)
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    app_url = os.getenv("APP_URL", os.getenv("BETTER_AUTH_URL", "http://127.0.0.1:8000")).rstrip("/")
    try:
        with httpx.Client(timeout=20) as client:
            token = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": f"{app_url}/api/auth/google/callback",
                    "grant_type": "authorization_code",
                },
            )
            token.raise_for_status()
            access_token = token.json().get("access_token")
            profile = client.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": f"Bearer {access_token}"})
            profile.raise_for_status()
            data = profile.json()
    except Exception:
        log.warning("Google OAuth callback failed", exc_info=True)
        return RedirectResponse("/login?error=google_auth_failed", status_code=302)
    email = str(data.get("email") or "").strip().lower()
    if not email:
        return RedirectResponse("/login?error=google_auth_failed", status_code=302)
    user = auth_store.oauth_user(str(data.get("name") or email.split("@")[0]), email, bool(data.get("email_verified", False)))
    token = auth_store.create_session(user["id"])
    response = RedirectResponse(_safe_redirect_path(post_auth_redirect), status_code=302)
    _set_session_cookie(response, token)
    response.delete_cookie("google_oauth_state", path="/")
    response.delete_cookie("post_auth_redirect", path="/")
    return response


@app.post("/api/auth/signup", dependencies=[Depends(verify_csrf), Depends(auth_rate_limiter.dependency)])
@_auth_guard
def signup(request: SignupRequest) -> JSONResponse:
    try:
        user = auth_store.create_user(request.name, request.email, request.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return _request_otp(user["email"], "signup")


@app.post("/api/auth/login", dependencies=[Depends(verify_csrf), Depends(auth_rate_limiter.dependency)])
@_auth_guard
def login(request: LoginRequest, req: Request) -> JSONResponse:
    ip = client_ip(req)
    email = request.email.strip().lower()
    if login_lockout.is_locked(email, ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please wait a few minutes and try again.")
    try:
        user = auth_store.check_login(email, request.password or "")
    except AuthError as exc:
        login_lockout.record_failure(email, ip)
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    login_lockout.reset(email, ip)
    if not user["verified"]:
        return _request_otp(user["email"], "signup", message="Account not verified yet. Enter the code we sent to verify it.")
    token = auth_store.create_session(user["id"])
    response = JSONResponse({"ok": True, "user": public_user(user)})
    _set_session_cookie(response, token)
    return response


@app.post("/api/auth/otp/request", dependencies=[Depends(verify_csrf), Depends(auth_rate_limiter.dependency)])
@_auth_guard
def request_otp(request: OTPRequest) -> JSONResponse:
    return _request_otp(request.email, request.purpose)


def _request_otp(email: str, purpose: str, message: str = "Verification code sent.") -> JSONResponse:
    try:
        result = auth_store.request_otp(email, purpose)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message, headers={"X-Auth-Wait": str(exc.details.get("wait", ""))}) from exc
    if result.get("skipped"):
        return JSONResponse({"ok": True, "message": message, "purpose": purpose, "email": email})
    delivered = send_otp_email(email, result["code"], purpose)
    allow_dev_otp = os.getenv("ALLOW_DEV_OTP", "false").lower() == "true"
    if not delivered and not allow_dev_otp:
        raise HTTPException(status_code=503, detail="Verification email could not be delivered. Check mail configuration and try again.")
    body: dict = {"ok": True, "message": message, "purpose": purpose, "email": email}
    if not delivered and allow_dev_otp:
        body["dev_code"] = result["code"]
        body["dev_note"] = "Development OTP mode is enabled."
    return JSONResponse(body)


@app.post("/api/auth/otp/verify", dependencies=[Depends(verify_csrf), Depends(auth_rate_limiter.dependency)])
@_auth_guard
def verify_otp(request: VerifyOTPRequest):
    try:
        auth_store.verify_otp(request.email, request.code, request.purpose)
    except AuthError as exc:
        response = JSONResponse({"ok": False, "detail": exc.message, **exc.details}, status_code=exc.status)
        response.headers["X-Auth-Lock"] = str(exc.details.get("lock_seconds", ""))
        return response

    user = auth_store.get_user_by_email(request.email)
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")

    if request.purpose == "signup":
        auth_store.mark_verified(user["email"])
        return {"ok": True, "redirect": "/login?verified=1"}

    if request.purpose == "reset":
        reset_token = auth_store.create_reset_challenge(user["email"])
        return {"ok": True, "reset_token": reset_token}

    token = auth_store.create_session(user["id"])
    response = JSONResponse({"ok": True, "redirect": "/app", "user": public_user(user)})
    _set_session_cookie(response, token)
    return response


@app.post("/api/auth/password/forgot", dependencies=[Depends(verify_csrf), Depends(auth_rate_limiter.dependency)])
@_auth_guard
def forgot_password(request: ForgotPasswordRequest) -> JSONResponse:
    return _request_otp(
        request.email,
        "reset",
        message="If an account exists for this email, we've sent a password reset code.",
    )


@app.post("/api/auth/password/reset/verify", dependencies=[Depends(verify_csrf), Depends(auth_rate_limiter.dependency)])
@_auth_guard
def verify_password_reset(request: ResetPasswordVerifyRequest) -> JSONResponse:
    verify = VerifyOTPRequest(email=request.email, code=request.code, purpose="reset")
    result = verify_otp(verify)
    if isinstance(result, JSONResponse):
        return result
    return JSONResponse(result)


@app.post("/api/auth/password/reset", dependencies=[Depends(verify_csrf), Depends(auth_rate_limiter.dependency)])
@_auth_guard
def reset_password(request: ResetPasswordRequest) -> JSONResponse:
    try:
        auth_store.reset_password(request.reset_token, request.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return JSONResponse({"ok": True, "message": "Your password has been changed successfully."})


@app.post("/api/auth/logout", dependencies=[Depends(verify_csrf)])
def logout(session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    if session_token:
        auth_store.delete_session(session_token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/api/auth/me")
def me(user: dict = Depends(require_session)):
    return {"user": public_user(user)}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if redirect := _frontend_redirect(request, "/"):
        return redirect
    return (BASE / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/app", response_class=HTMLResponse)
def app_page(request: Request):
    if redirect := _frontend_redirect(request, "/"):
        return redirect
    return _html("index.html")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if redirect := _frontend_redirect(request, "/login"):
        return redirect
    return _html("login.html")


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if redirect := _frontend_redirect(request, "/signup"):
        return redirect
    return _html("signup.html")


@app.get("/verify", response_class=HTMLResponse)
def verify_page(request: Request):
    if redirect := _frontend_redirect(request, "/verify"):
        return redirect
    return _html("otp.html")


@app.get("/health")
def health() -> dict:
    try:
        chunks = store.total_chunks()
    except Exception:
        chunks = 0
    try:
        source_count = len(store.sources())
    except Exception:
        source_count = 0
    return {"status": "ok", "documents": source_count, "chunks": chunks,
            "gemini": bool(os.getenv("GEMINI_API_KEY")), "rag_backend": RAG_BACKEND}


# ---------------------------------------------------------------------------
# RAG API (session protected)
# ---------------------------------------------------------------------------
@app.get("/api/formats")
def formats(user: dict = Depends(require_api_or_session)) -> dict:
    return {"extensions": sorted(SUPPORTED), "websites": True}


@app.get("/api/workspace/status")
def workspace_status(user: dict = Depends(require_session)) -> dict:
    # Configuration labels only: no keys or other users' document counts.
    from rag.gemini_keys import gemini_keys
    return {
        "database": "Supabase pgvector" if RAG_BACKEND == "vector" else "Local document index",
        "retrieval": "Local hash vectors" if RAG_BACKEND == "vector" and os.getenv("EMBEDDING_PROVIDER") == "local" else "Semantic vectors" if RAG_BACKEND == "vector" else "Keyword relevance",
        "generation": "Gemini configured" if gemini_keys() else "Retrieved passages only",
        "max_upload_mb": MAX_UPLOAD // 1024 // 1024,
    }


@app.post("/api/retrieval/test", dependencies=[Depends(verify_csrf), Depends(ask_rate_limiter.dependency)])
def test_retrieval(request: AskRequest, user: dict = Depends(require_api_or_session)) -> dict:
    results = store.search(request.question, request.top_k, request.sources, _owner_id(user))
    return {"sources": [
        {"number": i, "source": r["source"], "location": r["location"],
         "score": r["score"], "preview": r["text"]}
        for i, r in enumerate(results, 1)
    ]}


@app.get("/api/documents")
def documents(user: dict = Depends(require_api_or_session)) -> dict:
    return {"documents": store.sources(_owner_id(user))}


@app.get("/api/files")
def list_files(q: str = "", extension: str = "", sort: str = "newest",
               user: dict = Depends(require_api_or_session)) -> dict:
    owner_id = _owner_id(user)
    files = workspace_store.sync_sources(owner_id, store.sources(owner_id))
    if q or extension or sort != "newest":
        files = workspace_store.list_files(owner_id, q, extension, sort)
    bot_usage: dict[str, list[str]] = {}
    for bot in _owned_chatbots(user):
        for source in bot.get("sources", []):
            bot_usage.setdefault(source, []).append(bot.get("name", "Bot"))
    for item in files:
        item["bots"] = bot_usage.get(item["source"], [])
    return {"files": files}


def _index_uploaded_file(owner_id: int, source: str, name: str, content_type: str, data: bytes, stored_path: str) -> None:
    try:
        sections = extract_file(name, data)
        chunks = chunk_sections(name, sections)
        if not chunks:
            raise ValueError("No readable text was found")
        count = store.add(chunks, owner_id)
        metadata = analyze_file(name, data, sections)
        preview = "\n\n".join(f"{section.location}\n{section.text}" for section in sections)[:200_000]
        workspace_store.upsert_file(
            owner_id, source, name=name, mime_type=content_type,
            size_bytes=len(data), status="ready", chunks=count, metadata=metadata,
            preview=preview, stored_path=stored_path,
        )
    except Exception as exc:
        log.exception("Background indexing failed for %s", source)
        workspace_store.upsert_file(
            owner_id, source, name=name, mime_type=content_type,
            size_bytes=len(data), status="error", metadata={"error": str(exc)}, stored_path=stored_path,
        )


@app.post("/api/ingest/files",
          dependencies=[Depends(verify_csrf), Depends(ingest_rate_limiter.dependency)])
async def ingest_files(files: Annotated[list[UploadFile], File(...)], user: dict = Depends(require_api_or_session)) -> dict:
    output = []
    owner_id = _owner_id(user)
    existing_files = workspace_store.list_files(owner_id)
    existing_count = len(existing_files)
    existing_bytes = sum(int(item.get("size_bytes") or 0) for item in existing_files)
    for upload in files:
        name = Path(upload.filename or "unknown").name
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED:
            output.append({"source": name, "status": "error", "error": f"Unsupported type: {suffix or 'unknown'}"})
            continue
        data = await upload.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            output.append({"source": name, "status": "error", "error": f"File exceeds {MAX_UPLOAD // 1024 // 1024} MB"})
            continue
        if existing_count >= MAX_FILES_PER_USER:
            output.append({"source": name, "status": "error", "error": f"File limit reached ({MAX_FILES_PER_USER} files)"})
            continue
        if existing_bytes + len(data) > MAX_STORAGE:
            output.append({"source": name, "status": "error", "error": f"Storage limit reached ({MAX_STORAGE // 1024 // 1024} MB)"})
            continue
        record = workspace_store.upsert_file(
            owner_id, name, name=name, mime_type=upload.content_type or "application/octet-stream",
            size_bytes=len(data), status="processing",
        )
        stored_path = workspace_store.save_upload(record["id"], name, data)
        args = (owner_id, name, name, upload.content_type or "application/octet-stream", data, stored_path)
        if INDEX_INLINE:
            _index_uploaded_file(*args)
        else:
            INDEX_EXECUTOR.submit(_index_uploaded_file, *args)
        output.append({"source": name, "file_id": record["id"], "status": "queued"})
        existing_count += 1
        existing_bytes += len(data)
    return {"results": output}


@app.post("/api/ingest/url",
          dependencies=[Depends(verify_csrf), Depends(ingest_rate_limiter.dependency)])
def ingest_url(request: URLRequest, user: dict = Depends(require_api_or_session)) -> dict:
    owner_id = _owner_id(user)
    try:
        title, sections = extract_url(request.url)
        source = f"{title} — {request.url}"
        chunks = chunk_sections(source, sections)
        if not chunks:
            raise ValueError("No readable text was found")
        count = store.add(chunks, owner_id)
        preview = "\n\n".join(f"{section.location}\n{section.text}" for section in sections)[:200_000]
        saved = workspace_store.upsert_file(
            owner_id, source, name=title, mime_type="text/html", status="ready", chunks=count,
            metadata={"url": request.url, "sections": len(sections)}, preview=preview,
        )
        return {"source": source, "file_id": saved["id"], "status": "indexed", "chunks": count}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class FolderRequest(BaseModel):
    path: str = Field(..., description="Absolute path to a folder to scan and ingest recursively")
    max_mb: int = Field(25, ge=1, le=1000)


@app.post("/api/ingest/folder",
          dependencies=[Depends(verify_csrf), Depends(ingest_rate_limiter.dependency)])
def ingest_folder(request: FolderRequest, user: dict = Depends(require_api_or_session)) -> dict:
    root = Path(request.path).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a folder: {root}")
    report = ingest_directory(root, max_bytes=request.max_mb * 1024 * 1024)
    stored = store.add(report["chunks"], _owner_id(user)) if report["chunks"] else 0
    return {"root": report["root"], "files_found": report["files_found"],
            "indexed": report["indexed"], "errors": report["errors"],
            "chunk_count": len(report["chunks"]), "stored_chunks": stored}


@app.post("/api/ask",
          dependencies=[Depends(verify_csrf), Depends(ask_rate_limiter.dependency)])
def ask(request: AskRequest, user: dict = Depends(require_api_or_session)) -> dict:
    chatbot = None
    if request.chatbot_id:
        chatbot = next((c for c in _owned_chatbots(user) if str(c.get("id")) == request.chatbot_id), None)
        if not chatbot:
            raise HTTPException(status_code=404, detail="Chatbot not found")
    sources = request.sources or (chatbot.get("sources") if chatbot else None)
    results = store.search(request.question, request.top_k, sources, _owner_id(user))
    try:
        answer, provider = answer_with_sources(
            request.question, results, chatbot.get("name") if chatbot else None,
            instructions=chatbot.get("instructions", "") if chatbot else "",
        )
    except Exception:
        answer, provider = "I could not generate a full answer, but retrieved sources are still shown below.", "retrieval-error"
    source_list = [
        {"number": i, "source": r["source"], "location": r["location"], "score": r["score"], "preview": r["text"][:500]}
        for i, r in enumerate(results, 1)
    ]
    return {"answer": answer, "provider": provider, "sources": source_list,
            "selected_sources": sources, "chatbot": {"id": chatbot["id"], "name": chatbot["name"]} if chatbot else None}


@app.post("/api/documents/delete",
          dependencies=[Depends(verify_csrf), Depends(ingest_rate_limiter.dependency)])
def delete_document(request: DeleteRequest, user: dict = Depends(require_api_or_session)) -> dict:
    removed = store.delete_source(request.source, _owner_id(user))
    if not removed:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"source": request.source, "removed_chunks": removed}


@app.get("/api/files/{file_id}/preview")
def preview_file(file_id: str, user: dict = Depends(require_api_or_session)) -> dict:
    item = workspace_store.get_file(_owner_id(user), file_id)
    if not item:
        raise HTTPException(status_code=404, detail="File not found")
    content = item.get("preview", "")
    if not content and hasattr(store, "preview_source"):
        rows = store.preview_source(item["source"], 30, _owner_id(user))
        content = "\n\n".join(f"{row.get('location', '')}\n{row.get('text', '')}" for row in rows)
    return {"file": item, "content": content[:200_000]}


@app.get("/api/files/{file_id}/download")
def download_file(file_id: str, user: dict = Depends(require_api_or_session)):
    item = workspace_store.get_file(_owner_id(user), file_id)
    if not item or not item.get("stored_path") or not Path(item["stored_path"]).is_file():
        raise HTTPException(status_code=404, detail="Original file is not available")
    return FileResponse(item["stored_path"], filename=item["name"], media_type=item.get("mime_type") or None)


@app.patch("/api/files/{file_id}", dependencies=[Depends(verify_csrf), Depends(ingest_rate_limiter.dependency)])
def rename_file(file_id: str, request: FileRename, user: dict = Depends(require_api_or_session)) -> dict:
    owner_id = _owner_id(user)
    item = workspace_store.get_file(owner_id, file_id)
    if not item:
        raise HTTPException(status_code=404, detail="File not found")
    new_name = Path(request.name.strip()).name
    if not Path(new_name).suffix and item.get("extension"):
        new_name += item["extension"]
    if not new_name:
        raise HTTPException(status_code=422, detail="File name is required")
    old_source = item["source"]
    if new_name != old_source:
        available = {source["source"] for source in store.sources(owner_id)}
        if new_name in available:
            raise HTTPException(status_code=409, detail="A source with this name already exists")
        changed = store.rename_source(old_source, new_name, owner_id)
        if not changed:
            raise HTTPException(status_code=404, detail="Indexed source not found")
        for bot in _owned_chatbots(user):
            if old_source in bot.get("sources", []):
                updated_sources = [new_name if source == old_source else source for source in bot["sources"]]
                chatbot_store.update(str(bot["id"]), None, None, updated_sources)
    updated = workspace_store.rename_file(owner_id, file_id, new_name, new_name)
    return {"file": updated}


@app.delete("/api/files/{file_id}", dependencies=[Depends(verify_csrf), Depends(ingest_rate_limiter.dependency)])
def delete_file(file_id: str, user: dict = Depends(require_api_or_session)) -> dict:
    owner_id = _owner_id(user)
    item = workspace_store.get_file(owner_id, file_id)
    if not item:
        raise HTTPException(status_code=404, detail="File not found")
    removed = store.delete_source(item["source"], owner_id)
    for bot in _owned_chatbots(user):
        if item["source"] in bot.get("sources", []):
            chatbot_store.update(str(bot["id"]), None, None,
                                 [source for source in bot["sources"] if source != item["source"]])
    workspace_store.delete_file(owner_id, file_id)
    return {"ok": True, "removed_chunks": removed}


# ---------------------------------------------------------------------------
# Chatbots
# ---------------------------------------------------------------------------
@app.get("/api/chatbots")
def list_chatbots(user: dict = Depends(require_api_or_session)) -> dict:
    return {"chatbots": _owned_chatbots(user)}


@app.post("/api/chatbots",
          dependencies=[Depends(verify_csrf), Depends(auth_rate_limiter.dependency)])
def create_chatbot(request: ChatbotCreate, user: dict = Depends(require_api_or_session)) -> dict:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Chatbot name is required")
    owner_id = _owner_id(user)
    if request.sources:
        available = {s["source"] for s in store.sources(owner_id)}
        unknown = [s for s in request.sources if s not in available]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown sources: {', '.join(unknown)}")
    chatbot = chatbot_store.create(name, request.description.strip(), request.sources or [], owner_id)
    chatbot.update(workspace_store.upsert_bot_profile(
        owner_id, str(chatbot["id"]), avatar=request.avatar,
        instructions=request.instructions.strip(), enabled=request.enabled, color=request.color,
    ))
    return {"chatbot": chatbot}



@app.patch("/api/chatbots/{chatbot_id}",
           dependencies=[Depends(verify_csrf), Depends(auth_rate_limiter.dependency)])
def update_chatbot(chatbot_id: str, request: ChatbotUpdate, user: dict = Depends(require_api_or_session)) -> dict:
    owner_id = _owner_id(user)
    existing = next((bot for bot in _owned_chatbots(user) if str(bot.get("id")) == chatbot_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Chatbot not found")
    if request.sources is not None:
        available = {s["source"] for s in store.sources(owner_id)}
        unknown = [s for s in request.sources if s not in available]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown sources: {', '.join(unknown)}")
    chatbot = chatbot_store.update(chatbot_id, request.name, request.description, request.sources)
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")
    current = workspace_store.get_bot_profile(owner_id, chatbot_id)
    chatbot.update(workspace_store.upsert_bot_profile(
        owner_id, chatbot_id,
        avatar=request.avatar if request.avatar is not None else current["avatar"],
        instructions=request.instructions if request.instructions is not None else current["instructions"],
        enabled=request.enabled if request.enabled is not None else current["enabled"],
        color=request.color if request.color is not None else current["color"],
    ))
    return {"chatbot": chatbot}


@app.delete("/api/chatbots/{chatbot_id}",
            dependencies=[Depends(verify_csrf), Depends(auth_rate_limiter.dependency)])
def delete_chatbot(chatbot_id: str, user: dict = Depends(require_api_or_session)) -> dict:
    owner_id = _owner_id(user)
    if not any(str(bot.get("id")) == chatbot_id for bot in _owned_chatbots(user)):
        raise HTTPException(status_code=404, detail="Chatbot not found")
    if not chatbot_store.delete(chatbot_id):
        raise HTTPException(status_code=404, detail="Chatbot not found")
    workspace_store.delete_bot_profile(owner_id, chatbot_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Conversations and multi-bot collaboration
# ---------------------------------------------------------------------------
@app.get("/api/conversations")
def list_conversations(q: str = "", user: dict = Depends(require_api_or_session)) -> dict:
    return {"conversations": workspace_store.list_conversations(_owner_id(user), q)}


@app.post("/api/conversations", dependencies=[Depends(verify_csrf)])
def create_conversation(request: ConversationCreate, user: dict = Depends(require_api_or_session)) -> dict:
    allowed = {str(bot["id"]) for bot in _owned_chatbots(user) if bot.get("enabled", True)}
    bot_ids = [bot_id for bot_id in request.bot_ids if bot_id in allowed]
    return {"conversation": workspace_store.create_conversation(
        _owner_id(user), request.title, bot_ids,
    )}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: dict = Depends(require_api_or_session)) -> dict:
    conversation = workspace_store.get_conversation(_owner_id(user), conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation": conversation}


@app.patch("/api/conversations/{conversation_id}", dependencies=[Depends(verify_csrf)])
def update_conversation(conversation_id: str, request: ConversationUpdate,
                        user: dict = Depends(require_api_or_session)) -> dict:
    bot_ids = request.bot_ids
    if bot_ids is not None:
        allowed = {str(bot["id"]) for bot in _owned_chatbots(user) if bot.get("enabled", True)}
        bot_ids = [bot_id for bot_id in bot_ids if bot_id in allowed]
    conversation = workspace_store.update_conversation(
        _owner_id(user), conversation_id, title=request.title, bot_ids=bot_ids,
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation": conversation}


@app.delete("/api/conversations/{conversation_id}", dependencies=[Depends(verify_csrf)])
def delete_conversation(conversation_id: str, user: dict = Depends(require_api_or_session)) -> dict:
    if not workspace_store.delete_conversation(_owner_id(user), conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}


def _chatbot_response(bot: dict, content: str, attachments: list[str], history: list[dict],
                      owner_id: int = 0) -> dict:
    allowed_sources = list(dict.fromkeys([*bot.get("sources", []), *attachments]))
    intent = classify_intent(content)
    
    results = []
    source_list = []
    if intent == "DOCUMENT_QUESTION" and allowed_sources:
        search_query = rewrite_query(content, history)
        raw_results = store.search(search_query, 6, allowed_sources, owner_id)
        results = filter_relevant_results(search_query, raw_results)
        source_list = [
            {"number": index, "source": result["source"], "location": result["location"],
             "score": result["score"], "preview": result["text"][:500]}
            for index, result in enumerate(results, 1)
        ]

    try:
        answer, provider = answer_with_sources(
            content, results, bot.get("name"), instructions=bot.get("instructions", ""), history=history,
            sources_assigned=allowed_sources,
        )
    except Exception:
        answer, provider = "I could not generate a full answer, but retrieved sources are still shown below.", "retrieval-error"
    return {"bot": bot, "answer": answer, "provider": provider, "sources": source_list}


@app.post("/api/conversations/{conversation_id}/messages",
          dependencies=[Depends(verify_csrf), Depends(ask_rate_limiter.dependency)])
def send_conversation_message(conversation_id: str, request: ConversationMessageCreate,
                              user: dict = Depends(require_api_or_session)) -> dict:
    owner_id = _owner_id(user)
    conversation = workspace_store.get_conversation(owner_id, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    bots_by_id = {str(bot["id"]): bot for bot in _owned_chatbots(user) if bot.get("enabled", True)}
    requested_ids = request.bot_ids if request.bot_ids is not None else conversation.get("bot_ids", [])
    active_ids = [bot_id for bot_id in requested_ids if bot_id in bots_by_id]
    if not active_ids:
        raise HTTPException(status_code=400, detail="Select at least one enabled bot")
    available_sources = {item["source"] for item in store.sources(owner_id)}
    attachments = [source for source in request.attachments if source in available_sources]
    history = conversation.get("messages", [])
    user_message = workspace_store.add_message(
        owner_id, conversation_id, "user", request.content.strip(), attachments=attachments,
    )
    if conversation["title"] == "New conversation":
        clean_msg = request.content.strip()
        if classify_intent(clean_msg) != "SMALL_TALK":
            title = clean_msg[:50].strip()
            workspace_store.update_conversation(owner_id, conversation_id, title=title)
    workspace_store.update_conversation(owner_id, conversation_id, bot_ids=active_ids)

    responses = []
    workers = min(4, len(active_ids))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_chatbot_response, bots_by_id[bot_id], request.content.strip(), attachments, history, owner_id): bot_id
            for bot_id in active_ids
        }
        for future in as_completed(futures):
            bot = bots_by_id[futures[future]]
            try:
                result = future.result()
            except Exception as exc:
                result = {"bot": bot, "answer": f"I could not complete this response: {exc}",
                          "provider": "error", "sources": []}
            message = workspace_store.add_message(
                owner_id, conversation_id, "assistant", result["answer"], bot_id=str(bot["id"]),
                bot_name=bot["name"], sources=result["sources"], state="completed",
            )
            result["message"] = message
            responses.append(result)
    response_order = {bot_id: index for index, bot_id in enumerate(active_ids)}
    responses.sort(key=lambda item: response_order.get(str(item["bot"]["id"]), 999))
    return {"user_message": user_message, "responses": responses,
            "conversation": workspace_store.get_conversation(owner_id, conversation_id)}


@app.post("/api/conversations/{conversation_id}/messages/{message_id}/regenerate",
          dependencies=[Depends(verify_csrf), Depends(ask_rate_limiter.dependency)])
def regenerate_message(conversation_id: str, message_id: str,
                       user: dict = Depends(require_api_or_session)) -> dict:
    owner_id = _owner_id(user)
    conversation = workspace_store.get_conversation(owner_id, conversation_id)
    target = workspace_store.get_message(owner_id, message_id)
    if not conversation or not target or target.get("role") != "assistant":
        raise HTTPException(status_code=404, detail="Assistant message not found")
    if str(target.get("conversation_id")) != str(conversation_id):
        raise HTTPException(status_code=404, detail="Assistant message not found")
    messages = conversation.get("messages", [])
    target_index = next((index for index, message in enumerate(messages) if message["id"] == message_id), -1)
    if target_index < 0:
        raise HTTPException(status_code=404, detail="Assistant message not found")
    user_message = next((message for message in reversed(messages[:target_index]) if message["role"] == "user"), None)
    bot = next((item for item in _owned_chatbots(user) if str(item["id"]) == str(target.get("bot_id"))), None)
    if not user_message or not bot:
        raise HTTPException(status_code=400, detail="Cannot regenerate this response")
    result = _chatbot_response(bot, user_message["content"], user_message.get("attachments", []),
                               messages[:target_index], owner_id)
    workspace_store.delete_message(owner_id, message_id)
    message = workspace_store.add_message(
        owner_id, conversation_id, "assistant", result["answer"], bot_id=str(bot["id"]),
        bot_name=bot["name"], sources=result["sources"], state="completed",
    )
    result["message"] = message
    return result


@app.post("/api/conversations/{conversation_id}/messages/stream",
          dependencies=[Depends(verify_csrf), Depends(ask_rate_limiter.dependency)])
def stream_conversation_message(conversation_id: str, request: ConversationMessageCreate,
                                user: dict = Depends(require_api_or_session)):
    owner_id = _owner_id(user)
    conversation = workspace_store.get_conversation(owner_id, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    bots_by_id = {str(bot["id"]): bot for bot in _owned_chatbots(user) if bot.get("enabled", True)}
    requested_ids = request.bot_ids if request.bot_ids is not None else conversation.get("bot_ids", [])
    active_ids = [bot_id for bot_id in requested_ids if bot_id in bots_by_id]
    if not active_ids:
        raise HTTPException(status_code=400, detail="Select at least one enabled bot")
    available_sources = {item["source"] for item in store.sources(owner_id)}
    attachments = [source for source in request.attachments if source in available_sources]
    history = conversation.get("messages", [])
    user_message = workspace_store.add_message(
        owner_id, conversation_id, "user", request.content.strip(), attachments=attachments,
    )
    if conversation["title"] == "New conversation":
        clean_msg = request.content.strip()
        if classify_intent(clean_msg) != "SMALL_TALK":
            title = clean_msg[:50].strip()
            workspace_store.update_conversation(owner_id, conversation_id, title=title)
    workspace_store.update_conversation(owner_id, conversation_id, bot_ids=active_ids)

    def events():
        yield json.dumps({"type": "user", "message": user_message}, ensure_ascii=False) + "\n"
        with ThreadPoolExecutor(max_workers=min(4, len(active_ids))) as executor:
            futures = {
                executor.submit(_chatbot_response, bots_by_id[bot_id], request.content.strip(), attachments, history, owner_id): bot_id
                for bot_id in active_ids
            }
            for future in as_completed(futures):
                bot = bots_by_id[futures[future]]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"bot": bot, "answer": f"I could not complete this response: {exc}",
                              "provider": "error", "sources": []}
                message = workspace_store.add_message(
                    owner_id, conversation_id, "assistant", result["answer"], bot_id=str(bot["id"]),
                    bot_name=bot["name"], sources=result["sources"], state="completed",
                )
                yield json.dumps({"type": "assistant", "message": message, "provider": result["provider"]},
                                 ensure_ascii=False) + "\n"
        updated = workspace_store.get_conversation(owner_id, conversation_id)
        yield json.dumps({"type": "done", "conversation": updated}, ensure_ascii=False) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
