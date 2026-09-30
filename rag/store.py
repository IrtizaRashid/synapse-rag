from __future__ import annotations

import json
import threading
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .ingest import Chunk


class KnowledgeStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.chunks: list[Chunk] = []
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.chunks = [Chunk(**item) for item in raw]
        self._rebuild()

    def _save(self) -> None:
        self.path.write_text(json.dumps([c.to_dict() for c in self.chunks], ensure_ascii=False, indent=2), encoding="utf-8")

    def _rebuild(self) -> None:
        if not self.chunks:
            self.vectorizer, self.matrix = None, None
            return
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=60000)
        self.matrix = self.vectorizer.fit_transform([c.text for c in self.chunks])

    def add(self, chunks: list[Chunk], owner_id: int = 0) -> int:
        if not chunks:
            return 0
        with self.lock:
            for c in chunks:
                c.owner_id = owner_id
            sources = {c.source for c in chunks}
            self.chunks = [c for c in self.chunks if not (getattr(c, "owner_id", 0) == owner_id and c.source in sources)]
            self.chunks.extend(chunks)
            self._rebuild()
            self._save()
        return len(chunks)

    def delete_source(self, source: str, owner_id: int = 0) -> int:
        with self.lock:
            before = len(self.chunks)
            self.chunks = [c for c in self.chunks if not (getattr(c, "owner_id", 0) == owner_id and c.source == source)]
            removed = before - len(self.chunks)
            if removed:
                self._rebuild()
                self._save()
            return removed

    def rename_source(self, source: str, new_source: str, owner_id: int = 0) -> int:
        with self.lock:
            changed = 0
            for chunk in self.chunks:
                if getattr(chunk, "owner_id", 0) == owner_id and chunk.source == source:
                    chunk.source = new_source
                    changed += 1
            if changed:
                self._save()
            return changed

    def preview_source(self, source: str, limit: int = 30, owner_id: int = 0) -> list[dict]:
        with self.lock:
            return [
                {"location": chunk.location, "text": chunk.text}
                for chunk in self.chunks
                if getattr(chunk, "owner_id", 0) == owner_id and chunk.source == source
            ][: max(1, min(limit, 100))]

    def sources(self, owner_id: int = 0) -> list[dict]:
        counts: dict[str, int] = {}
        for chunk in self.chunks:
            if getattr(chunk, "owner_id", 0) == owner_id:
                counts[chunk.source] = counts.get(chunk.source, 0) + 1
        return [{"source": source, "chunks": count} for source, count in sorted(counts.items())]

    def total_chunks(self, owner_id: int = 0) -> int:
        return sum(1 for chunk in self.chunks if getattr(chunk, "owner_id", 0) == owner_id)

    def search(self, question: str, top_k: int = 5, sources: list[str] | None = None,
               owner_id: int = 0) -> list[dict]:
        if not self.chunks or self.vectorizer is None:
            return []
        with self.lock:
            query = self.vectorizer.transform([question])
            scores = cosine_similarity(query, self.matrix).ravel()
            allowed = set(sources) if sources is not None else None
            candidates = [
                i for i, chunk in enumerate(self.chunks)
                if getattr(chunk, "owner_id", 0) == owner_id and (allowed is None or chunk.source in allowed)
            ]
            if not candidates:
                return []
            indices = sorted(candidates, key=lambda i: scores[i], reverse=True)[:max(1, min(top_k, 20))]
            return [
                {**self.chunks[i].to_dict(), "score": round(float(scores[i]), 4)}
                for i in indices
                if scores[i] > 0
            ]

