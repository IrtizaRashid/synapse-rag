# Client Knowledge Base

Synapse RAG is prepared for client review on September 9, 2026.

The platform supports private document upload, website ingestion, scoped assistants, saved conversations, source-grounded answers, source previews, downloads, and retrieval testing.

The recommended production architecture uses a Next.js workspace frontend, a FastAPI RAG backend, Supabase pgvector for vector retrieval, local workspace metadata for file previews, and Gemini for generated answers with citations.

For production signups, email delivery must be configured with Resend or SMTP. Development OTP mode is disabled unless `ALLOW_DEV_OTP=true`.

The first client demo question should ask: What production architecture does Synapse RAG use?
