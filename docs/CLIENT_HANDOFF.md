# Synapse RAG Client Handoff

Synapse is a client-ready RAG workspace built around the existing FastAPI and Supabase/pgvector architecture in this project. The interface follows the professional pattern used by modern RAG products such as Dify: knowledge bases, scoped assistants, grounded chat, source citations, and retrieval testing are all first-class workspace views.

Reference used for the product model: Dify's RAG product page describes multi-source ingestion, chunking, retrieval, answer generation, and source references as core RAG capabilities: https://www.dify.ai/rag

## Architecture

- Next.js app in `frontend/` provides the authenticated workspace UI.
- FastAPI in `app.py` provides auth, ingestion, file management, chatbots, conversations, RAG answer generation, and retrieval testing APIs.
- Supabase stores vector chunks when `RAG_BACKEND=vector`; local TF-IDF storage remains available for offline development.
- Local SQLite stores account/session metadata when `AUTH_BACKEND=local`; Supabase auth tables are supported when `AUTH_BACKEND=supabase`.
- Upload previews and workspace metadata are stored under `data/` by default.

## Main Features

- Document upload for PDF, DOCX, PPTX, CSV, TXT, Markdown, images, and code/text files.
- Background document indexing, so upload requests return quickly while extraction, OCR, embeddings, and Supabase writes continue server-side.
- Website page ingestion with server-side URL protections.
- Knowledge library with search, preview, rename, download, and delete.
- Assistant builder with instructions, enabled state, color, avatar, and source scoping.
- Multi-assistant conversations with saved chat history.
- Cited answers with source cards and source preview dialogs.
- Retrieval playground with source filtering, top-k control, score display, and timing.
- Workspace status panel showing configured database, retrieval, generation, and upload limits.

## Local Run

Start the API:

```powershell
C:\Users\irtiz\rag-platform\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:3000.

## Docker Preview

```powershell
docker compose -f docker-compose.preview.yml up --build
```

Open http://127.0.0.1:3000.

## Production Notes

- Set `ALLOW_DEV_OTP=false` or omit it in production.
- Configure either `RESEND_API_KEY` or SMTP before allowing signups.
- Use `COOKIE_SECURE=true` behind HTTPS.
- Use `AUTH_BACKEND=supabase` and `RAG_BACKEND=vector` for a Supabase-backed deployment.
- Tune `INDEX_WORKERS` for background indexing concurrency. Start with `2` unless the host has enough CPU/memory for more OCR and embedding work.
- Keep `SUPABASE_SERVICE_ROLE_KEY`, Gemini keys, and email credentials server-side only.
- Run the SQL files in `supabase/` before switching a new Supabase project to vector mode.

## Verification

Current automated verification:

```text
70 backend tests passing
Next.js production build passing
npm audit passing with 0 vulnerabilities
```
