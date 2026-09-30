"""Semantic embeddings via Gemini for the pgvector store.

Uses the same GEMINI_API_KEY as chat answers. No extra provider needed.
Model/dimension can be tuned via env (GEMINI_EMBED_MODEL, EMBED_DIM).
"""

from __future__ import annotations

import os
import hashlib
import logging
import math
import re

from .gemini_keys import next_gemini_key

BATCH = 50
log = logging.getLogger("rag.embeddings")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class LocalHashEmbedder:
    """Dependency-free fallback for indexing when Gemini embeddings are unavailable.

    The vector is a normalized hashed bag of words. It is not as semantic as
    Gemini, but it keeps uploads searchable and prevents provider auth problems
    from turning valid documents into failed files.
    """

    def __init__(self, dim: int | None = None):
        self.dim = int(dim or os.getenv("EMBED_DIM", "768"))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_text(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_text(text)

    def _embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = TOKEN_RE.findall(text.lower())
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        length = math.sqrt(sum(value * value for value in vector))
        if not length:
            return vector
        return [value / length for value in vector]


class GeminiEmbedder:
    def __init__(self, model: str | None = None, dim: int | None = None):
        self.model = model or os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
        self.dim = int(dim or os.getenv("EMBED_DIM", "768"))
        self._clients = {}
        self._fallback = LocalHashEmbedder(self.dim)
        self._fallback_notice_logged = False

    def _get_client(self):
        key = next_gemini_key()
        if key not in self._clients:
            from google import genai

            self._clients[key] = genai.Client(api_key=key)
        return self._clients[key]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        result = self._embed([text], "RETRIEVAL_QUERY")
        return result[0] if result else [0.0] * self.dim

    def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        if not texts:
            return []
        if os.getenv("EMBEDDING_PROVIDER", "gemini").strip().lower() == "local":
            return self._fallback.embed_documents(texts)
        try:
            client = self._get_client()
            output: list[list[float]] = []
            for start in range(0, len(texts), BATCH):
                batch = texts[start : start + BATCH]
                response = client.models.embed_content(
                    model=self.model,
                    contents=batch,
                    config={"task_type": task, "output_dimensionality": self.dim},
                )
                for emb in response.embeddings:
                    output.append([float(v) for v in emb.values])
            return output
        except Exception as exc:
            if os.getenv("EMBEDDING_LOCAL_FALLBACK", "true").strip().lower() == "false":
                raise
            if not self._fallback_notice_logged:
                log.warning("Gemini embeddings unavailable; using local hash embeddings: %s", exc)
                self._fallback_notice_logged = True
            return self._fallback.embed_documents(texts)
