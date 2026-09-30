"""pgvector-backed knowledge store on Supabase Postgres.

Chunks are embedded with Gemini and retrieved through owner-scoped pgvector
RPCs. Every operation is tenant-filtered; owner 0 is reserved for trusted API
key automation such as n8n.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger("rag.vector")
INSERT_BATCH = 50


class SupabaseVectorStore:
    def __init__(self, url: str, anon_key: str, service_role_key: str, embedder,
                 client: httpx.Client | None = None):
        self.base = url.rstrip("/")
        self._anon = anon_key
        self._service = service_role_key
        self._embedder = embedder
        self._client = client or httpx.Client(timeout=40)

    def _headers(self, prefer: str = "return=minimal") -> dict:
        return {
            "apikey": self._anon,
            "Authorization": f"Bearer {self._service}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        }

    def _table_url(self, table: str) -> str:
        return f"{self.base}/rest/v1/{table}"

    def _rpc_url(self, function: str) -> str:
        return f"{self.base}/rest/v1/rpc/{function}"

    def _check(self, response: httpx.Response, context: str) -> httpx.Response:
        if response.status_code == 404:
            body = response.text
            if "PGRST205" in body or "Could not find the table" in body or "Could not find the function" in body:
                raise RuntimeError(
                    f"{context} failed because the vector schema is missing. "
                    "Run supabase/rag_vector.sql in the Supabase SQL editor."
                )
        response.raise_for_status()
        return response

    def add(self, chunks, owner_id: int = 0) -> int:
        if not chunks:
            return 0
        texts = [chunk.text for chunk in chunks]
        vectors = self._embedder.embed_documents(texts)
        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding count mismatch; aborting ingest.")
        sources = {chunk.source for chunk in chunks}
        for source in sources:
            self._check(
                self._client.delete(
                    self._table_url("rag_chunks"),
                    params={"source": f"eq.{source}", "owner_id": f"eq.{owner_id}"},
                    headers=self._headers(),
                ),
                "delete",
            )
        rows = [
            {"source": chunk.source, "location": chunk.location, "text": chunk.text,
             "embedding": vector, "owner_id": owner_id}
            for chunk, vector in zip(chunks, vectors)
        ]
        for start in range(0, len(rows), INSERT_BATCH):
            self._check(
                self._client.post(self._table_url("rag_chunks"), json=rows[start:start + INSERT_BATCH],
                                  headers=self._headers()),
                "insert",
            )
        log.info("Indexed %d chunks across %d sources for owner %s", len(rows), len(sources), owner_id)
        return len(rows)

    def search(self, question: str, top_k: int = 5, sources: list[str] | None = None,
               owner_id: int = 0) -> list[dict]:
        payload = {
            "query_embedding": self._embedder.embed_query(question),
            "top_k": max(1, min(top_k, 20)),
            "sources": sources,
            "owner": owner_id,
        }
        response = self._check(
            self._client.post(self._rpc_url("search_chunks"), json=payload, headers=self._headers()), "search"
        )
        body = response.json()
        rows = body if isinstance(body, list) else []
        return [
            {"source": row["source"], "location": row["location"], "text": row["text"],
             "score": round(float(row["score"]), 4)}
            for row in rows if float(row.get("score", 0)) > 0
        ]

    @staticmethod
    def _count(response: httpx.Response, fallback: int = 1) -> int:
        try:
            return int(response.headers.get("content-range", "").rsplit("/", 1)[-1])
        except (ValueError, IndexError):
            return fallback

    def delete_source(self, source: str, owner_id: int = 0) -> int:
        response = self._check(
            self._client.delete(
                self._table_url("rag_chunks"),
                params={"source": f"eq.{source}", "owner_id": f"eq.{owner_id}"},
                headers=self._headers("return=minimal,count=exact"),
            ),
            "delete",
        )
        return self._count(response)

    def rename_source(self, source: str, new_source: str, owner_id: int = 0) -> int:
        response = self._check(
            self._client.patch(
                self._table_url("rag_chunks"),
                params={"source": f"eq.{source}", "owner_id": f"eq.{owner_id}"},
                json={"source": new_source},
                headers=self._headers("return=minimal,count=exact"),
            ),
            "rename",
        )
        return self._count(response)

    def preview_source(self, source: str, limit: int = 30, owner_id: int = 0) -> list[dict]:
        response = self._check(
            self._client.get(
                self._table_url("rag_chunks"),
                params={"select": "location,text", "source": f"eq.{source}",
                        "owner_id": f"eq.{owner_id}", "limit": str(max(1, min(limit, 100)))},
                headers=self._headers(),
            ),
            "preview",
        )
        rows = response.json()
        return rows if isinstance(rows, list) else []

    def sources(self, owner_id: int = 0) -> list[dict]:
        rpc = self._client.post(self._rpc_url("list_rag_sources"), json={"owner": owner_id},
                                headers=self._headers())
        if rpc.status_code < 400:
            rows = rpc.json()
            if isinstance(rows, list):
                return [{"source": row["source"], "chunks": int(row["chunks"])} for row in rows]
        rows = self._check(
            self._client.get(
                self._table_url("rag_chunks"),
                params={"select": "source", "owner_id": f"eq.{owner_id}"},
                headers=self._headers(),
            ),
            "select",
        ).json()
        counts: dict[str, int] = {}
        for row in rows if isinstance(rows, list) else []:
            counts[row["source"]] = counts.get(row["source"], 0) + 1
        return [{"source": source, "chunks": count} for source, count in sorted(counts.items())]

    def total_chunks(self, owner_id: int = 0) -> int:
        response = self._check(
            self._client.head(
                self._table_url("rag_chunks"),
                params={"select": "id", "owner_id": f"eq.{owner_id}"},
                headers=self._headers("count=exact"),
            ),
            "count",
        )
        return self._count(response, 0)
