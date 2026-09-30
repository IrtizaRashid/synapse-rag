# n8n workflow

Workflow file: `n8n/workflows/rag-workflow.json`

It contains four independent webhook branches:

1. `POST /webhook/rag/upload` - accepts JSON containing `filename`, `mime_type`, and `content_base64`; forwards the decoded file to OCR/indexing.
2. `POST /webhook/rag/website` - accepts `{ "url": "https://..." }`; extracts and indexes the page.
3. `POST /webhook/rag/ask` - accepts `question`, `top_k`, and either a non-empty `sources` array or a `chatbot_id`. The validation node rejects requests with neither, so retrieval and Gemini only see selected files or chatbot-connected files.
4. `POST /webhook/rag/chatbot` - accepts `name`, `description`, and a non-empty `sources` array; creates a chatbot through the RAG API.

## Start and import

1. Start the RAG API on port 8000 with `start.bat`.
2. Start Docker Desktop.
3. In this project directory run:

```bash
docker compose -f docker-compose.n8n.yml up -d
docker compose -f docker-compose.n8n.yml exec n8n n8n import:workflow --input=/workflows/rag-workflow.json
docker compose -f docker-compose.n8n.yml exec n8n n8n update:workflow --id=8b4f4d41-73b8-4bbd-b6e8-a332f8ab7f21 --active=true
docker compose -f docker-compose.n8n.yml restart n8n
```

Open http://localhost:5678 and complete the local owner-account screen if prompted.

Production n8n URL:

```text
https://n8n.rag.irtizarashid.shop
```

## Ask example

```json
{
  "question": "What does the selected handbook say?",
  "top_k": 5,
  "sources": ["handbook.pdf", "policies.docx"]
}
```

Unselected sources are excluded by both the n8n validation layer and the RAG API retrieval filter.

## Upload example

```json
{
  "filename": "handbook.pdf",
  "mime_type": "application/pdf",
  "content_base64": "JVBERi0x..."
}
```

## Website example

```json
{
  "url": "https://example.com/policy"
}
```

## Create chatbot example

```json
{
  "name": "Policy assistant",
  "description": "Answers only from selected policy files.",
  "sources": ["handbook.pdf", "policies.docx"]
}
```
