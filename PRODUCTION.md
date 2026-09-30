# Production checklist

This checklist is safe to commit. It must not contain real API keys, passwords,
JWTs, database URLs, or other secrets.

## 1. Environment

Set these values on the production server through environment variables or a
server-only `.env` file that is never committed.

Required:

```env
GEMINI_API_KEY=<primary-gemini-key>
GEMINI_API_KEYS=<comma-separated-gemini-keys>
GEMINI_MODEL=gemini-2.5-flash
GEMINI_EMBED_MODEL=gemini-embedding-001
EMBED_DIM=768

SUPABASE_URL=<supabase-project-url>
SUPABASE_ANON_KEY=<supabase-anon-jwt>
SUPABASE_SERVICE_ROLE_KEY=<supabase-service-role-jwt>

AUTH_BACKEND=supabase
RAG_BACKEND=vector

RESEND_API_KEY=<resend-api-key>
MAIL_FROM=RAG Platform <noreply@your-verified-domain>

RAG_API_KEYS=<comma-separated-server-accepted-api-keys>
RAG_API_KEY=<key-used-by-n8n>
N8N_ENCRYPTION_KEY=<long-random-key>

COOKIE_SECURE=true
TRUST_PROXY=true
ALLOWED_HOSTS=rag.example.com
ALLOWED_ORIGINS=https://rag.example.com,https://n8n.rag.example.com
```

Recommended:

```env
MAX_UPLOAD_MB=25
MAX_FILES_PER_USER=200
MAX_STORAGE_MB=1024
TOP_K=5
RATE_LIMIT_ENABLED=true
AUTH_RATE_LIMIT=10
ASK_RATE_LIMIT=20
INGEST_RATE_LIMIT=10
LOGIN_MAX_FAILURES=5
LOGIN_LOCK_SECONDS=900
SESSION_TTL_DAYS=7
LOG_LEVEL=INFO
LOG_FORMAT=json
```

## 2. Supabase

- [ ] Create or select the Supabase project.
- [ ] Run `supabase/schema.sql`.
- [ ] Run `supabase/chatbots.sql`.
- [ ] Run `supabase/rag_vector.sql`.
- [ ] Confirm these tables exist:
  - `auth_users`
  - `auth_otp_codes`
  - `auth_sessions`
  - `chatbots`
  - `rag_chunks`
- [ ] Confirm vector search RPC functions exist.
- [ ] Rotate service-role keys before public production if they were exposed during setup.

## 3. Resend

- [ ] Verify sender domain in Resend.
- [ ] Add required DNS records for SPF/DKIM.
- [ ] Set `MAIL_FROM` to an address on the verified domain.
- [ ] Test signup OTP email.
- [ ] Test login OTP email.

## 4. Domains and DNS

Target domains:

```text
https://rag.example.com
https://n8n.rag.example.com
```

DNS:

- [ ] Add `A` or `AAAA` record for `rag`.
- [ ] Add `A` or `AAAA` record for `n8n.rag`.
- [ ] Keep proxy disabled until the first SSL test passes, if using Cloudflare.
- [ ] Confirm both domains resolve to the deployment server.

## 5. Docker and Caddy

- [ ] Replace example domains in `Caddyfile`.
- [ ] Replace example domains in `docker-compose.yml`.
- [ ] Keep n8n pinned to a known image version.
- [ ] Run `docker compose config`.
- [ ] Run `python scripts/check_production_config.py`.
- [ ] Run `docker compose up -d --build`.
- [ ] Confirm container health checks are healthy.
- [ ] Confirm Caddy issued TLS certificates.

## 6. n8n

- [ ] Start n8n.
- [ ] Set `N8N_ENCRYPTION_KEY` before creating production credentials.
- [ ] Complete owner account setup.
- [ ] Import `n8n/workflows/rag-workflow.json`.
- [ ] Activate workflow `8b4f4d41-73b8-4bbd-b6e8-a332f8ab7f21`.
- [ ] Test `/webhook/rag/upload`.
- [ ] Test `/webhook/rag/website`.
- [ ] Test `/webhook/rag/ask`.
- [ ] Test `/webhook/rag/chatbot`.

## 7. Storage and backups

Current state:

- Uploaded files are stored on local disk inside the Docker data volume.
- Workspace metadata is stored in SQLite inside the Docker data volume.
- Vector chunks are stored in Supabase when `RAG_BACKEND=vector`.

Before serious production:

- [ ] Back up Docker volumes regularly.
- [ ] Back up Supabase database regularly.
- [ ] Decide whether uploaded files should move to object storage such as S3, R2, or Supabase Storage.
- [ ] Document restore steps and test them once.

## 8. Security

- [ ] Never commit `.env`.
- [ ] Never commit real keys in docs or examples.
- [ ] Rotate any keys that were pasted into chat or logs.
- [ ] Use long random values for `RAG_API_KEYS`.
- [ ] Use a long random value for `N8N_ENCRYPTION_KEY`.
- [ ] Keep `COOKIE_SECURE=true` behind HTTPS.
- [ ] Keep `TRUST_PROXY=true` only behind a trusted proxy.
- [ ] Review Cloudflare firewall or rate limiting options.
- [ ] Consider antivirus scanning for public uploads.
- [ ] Add per-user quotas for upload count, storage size, and request volume.
- [ ] Confirm upload quotas match the expected production plan.

## 9. Testing

- [ ] `GET /health` returns `status: ok`.
- [ ] Health response shows `gemini: true`.
- [ ] Health response shows `rag_backend: vector`.
- [ ] Signup works.
- [ ] OTP email arrives.
- [ ] Login works.
- [ ] File upload works.
- [ ] Website ingestion works.
- [ ] Chat answer includes citations.
- [ ] n8n webhooks work.
- [ ] Docker health checks are healthy.

## 10. Future improvements

- [ ] Move heavy ingestion to a background worker queue.
- [x] Add structured JSON logging.
- [x] Add request IDs.
- [ ] Add Sentry or another error tracker.
- [ ] Add admin controls for users, files, and bots.
- [ ] Add Playwright browser tests.
- [x] Add CI for tests, Magic UI build, and Docker Compose validation.
- [x] Add production config checker script.
- [ ] Add deployment automation.
- [ ] Add load tests for OCR, embeddings, and multi-bot streaming.
