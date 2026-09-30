# Synapse RAG

An end-to-end RAG workspace with background document ingestion, knowledge-base management, scoped assistants, saved conversations, cited answers, and a retrieval playground. It uses FastAPI for ingestion/RAG APIs, Next.js for the client workspace, Supabase pgvector for production retrieval, and local storage fallbacks for development.

## Setup (Windows)

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
copy .env.example .env
```

Set `GEMINI_API_KEY` in `.env` for generated answers. Without it, retrieval and source previews still work.

## Run

```bash
.venv/Scripts/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open the API at http://127.0.0.1:8000.

## Run the Next.js frontend

The new frontend is a Next.js + React + TypeScript app in `frontend/`. Keep the FastAPI backend running on port `8000`, then start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open the workspace at http://127.0.0.1:3000. The Next app proxies `/api/*` and `/health` to FastAPI.

## Docker preview

```bash
docker compose -f docker-compose.preview.yml up --build
```

Open http://127.0.0.1:3000.

## Supported inputs

- `.pdf`: native text extraction; pages with little/no text are rendered and OCRed
- `.docx`: paragraphs/tables plus OCR of embedded images
- `.pptx`: slide text/tables plus OCR of embedded images
- `.csv`, `.txt`, `.md`
- `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, `.tiff`
- `http://` and `https://` website URLs

## API

- `POST /api/ingest/files` — multipart field `files`
- `POST /api/ingest/url` — JSON `{ "url": "https://example.com" }`
- `POST /api/ask` — JSON `{ "question": "...", "top_k": 5 }`
- `GET /api/documents`
- `DELETE /api/documents/{source}`
- `GET /health`

## Notes

Client handoff details are in `docs/CLIENT_HANDOFF.md`. Do not upload confidential documents to an untrusted machine. Website ingestion extracts the supplied page only; it does not crawl an entire domain.

## Authentication Setup

This project uses the existing FastAPI authentication service because the backend and RAG ownership model are Python/FastAPI based. Better Auth was reviewed as requested; it is a TypeScript runtime, so a full migration would require a separate Node auth service and a production data migration. The current implementation has been hardened with production-style controls: email/password accounts, Google OAuth, verified email, 3-minute password-reset OTPs, hashed OTP storage, maximum 3 OTP attempts, one-time reset challenges, HttpOnly session cookies, CSRF origin checks, rate limiting, and session revocation after password reset.

Required environment variables:

```bash
APP_NAME=Synapse
APP_URL=https://your-api-domain.example.com
AUTH_SECRET=replace-with-a-long-random-secret
OTP_PEPPER=replace-with-a-long-random-secret
RESET_TOKEN_PEPPER=replace-with-a-long-random-secret
PASSWORD_MIN_LENGTH=12
OTP_TTL_SECONDS=180
MAX_OTP_ATTEMPTS=3
OTP_RESEND_COOLDOWN=60
RESET_TOKEN_TTL_SECONDS=600
COOKIE_SECURE=true
ALLOWED_ORIGINS=https://your-frontend-domain.example.com
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
RESEND_API_KEY=
EMAIL_FROM=Synapse <auth@your-domain.example>
```

Google OAuth setup:

1. In Google Cloud Console, create an OAuth 2.0 Web Client.
2. Add the authorized JavaScript origin for the frontend, for example `https://your-frontend-domain.example.com`.
3. Add this redirect URI: `https://your-api-domain.example.com/api/auth/google/callback`.
4. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `APP_URL` on the backend host.

Resend setup:

1. Verify your sending domain in Resend.
2. Create a server-side API key.
3. Set `RESEND_API_KEY` and `EMAIL_FROM` on the backend host.
4. Never expose `RESEND_API_KEY` to the frontend.

Supabase/Postgres migration:

Run `supabase/schema.sql` in the Supabase SQL editor. It now includes `auth_password_reset_challenges`, which stores only hashed reset challenge tokens. Do not reset or drop existing auth tables in production.

Local development:

- Use `ALLOW_DEV_OTP=true` only for local development if you need codes returned to the browser.
- Keep `COOKIE_SECURE=false` locally over HTTP.
- Use `COOKIE_SECURE=true` in production HTTPS.

Security notes:

- Login errors are generic.
- Password reset requests do not reveal whether an email exists.
- OTPs expire after 180 seconds and are invalidated after 3 incorrect attempts.
- Password reset revokes existing sessions.
- RAG files, chats, assistants, and vector retrieval are scoped by the authenticated owner ID on the server.
