"""Unit tests for the pgvector store against an in-memory fake PostgREST."""

import json

import httpx

from rag.ingest import chunk_sections, extract_file
from rag.vector_store import SupabaseVectorStore


class _StubEmbedder:
    dim = 4

    def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0, 0.0]] * len(texts)

    def embed_query(self, text):
        return [1.0, 0.0, 0.0, 0.0]


class _FakeVectorDB:
    def __init__(self, missing_schema: bool = False):
        self.missing_schema = missing_schema
        self.chunks = []
        self.next_id = 1
        self.search_rows = []
        self.last_search_body = None

    @staticmethod
    def _match(row, params) -> bool:
        for key, value in params.items():
            if key in ("select", "order", "limit"):
                continue
            if value.startswith("eq."):
                if str(row.get(key)) != value[3:]:
                    return False
        return True

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.missing_schema:
            return httpx.Response(404, json={"code": "PGRST205"})
        path = request.url.path
        method = request.method
        body = json.loads(request.content) if request.content else {}

        if path.endswith("rag_chunks"):
            if method == "HEAD":
                rows = [c for c in self.chunks if self._match(c, request.url.params)]
                total = len(rows)
                return httpx.Response(200, headers={"content-range": f"0-{max(0, total - 1)}/{total}"})
            if method == "GET":
                rows = [c for c in self.chunks if self._match(c, request.url.params)]
                return httpx.Response(200, json=rows)
            if method == "POST":
                for item in body if isinstance(body, list) else [body]:
                    row = {"id": self.next_id, **item}
                    self.next_id += 1
                    self.chunks.append(row)
                return httpx.Response(201, json=[])
            if method == "DELETE":
                before = len(self.chunks)
                self.chunks = [c for c in self.chunks if not self._match(c, request.url.params)]
                removed = before - len(self.chunks)
                return httpx.Response(200, json=[], headers={"content-range": f"*/{removed}"})
            if method == "PATCH":
                matched = [c for c in self.chunks if self._match(c, request.url.params)]
                for row in matched:
                    row.update(body)
                return httpx.Response(200, json=[], headers={"content-range": f"*/{len(matched)}"})

        if path.endswith("rpc/search_chunks"):
            self.last_search_body = body
            return httpx.Response(200, json=self.search_rows)

        return httpx.Response(404, json={"code": "PGRST205"})


def _store(fake=None):
    fake = fake or _FakeVectorDB()
    client = httpx.Client(transport=httpx.MockTransport(fake.handler))
    return SupabaseVectorStore("https://fake.supabase.co", "anon", "service", _StubEmbedder(), client=client), fake


def test_add_search_sources_delete():
    store, fake = _store()
    chunks = chunk_sections("doc.md", extract_file("doc.md", b"# Topic\nVector search is fast and semantic."))
    assert len(chunks) >= 1
    assert store.add(chunks) == len(chunks)
    assert len(fake.chunks) == len(chunks)
    assert all(c["embedding"] == [1.0, 0.0, 0.0, 0.0] for c in fake.chunks)

    assert store.sources() == [{"source": "doc.md", "chunks": len(chunks)}]
    assert store.total_chunks() == len(chunks)

    fake.search_rows = [{"id": 1, "source": "doc.md", "location": "document text",
                         "text": "some snippet", "score": 0.92}]
    results = store.search("what is vector search?", top_k=5, sources=["doc.md"])
    assert results and results[0]["score"] == 0.92
    # RPC received the query embedding and source filter
    assert fake.last_search_body["query_embedding"] == [1.0, 0.0, 0.0, 0.0]
    assert fake.last_search_body["sources"] == ["doc.md"]

    assert store.delete_source("doc.md") == len(chunks)
    assert store.total_chunks() == 0


def test_reingest_replaces_old_source_chunks():
    store, fake = _store()
    chunks = chunk_sections("doc.md", extract_file("doc.md", b"first version"))
    assert store.add(chunks) == len(chunks)
    first_id = fake.chunks[0]["id"]
    chunks2 = chunk_sections("doc.md", extract_file("doc.md", b"second version of the document"))
    assert store.add(chunks2) == len(chunks2)
    # Old rows for the source are gone, new rows present
    assert all(c["id"] != first_id for c in fake.chunks)
    assert store.total_chunks() == len(chunks2)


def test_missing_schema_raises_helpful_error():
    fake = _FakeVectorDB(missing_schema=True)
    store, _ = _store(fake)
    try:
        store.total_chunks()
        assert False, "expected RuntimeError about missing schema"
    except RuntimeError as exc:
        assert "rag_vector.sql" in str(exc)


def test_search_without_sources_omits_filter():
    store, fake = _store()
    fake.search_rows = []
    store.search("query here", top_k=4, sources=None)
    assert fake.last_search_body["sources"] is None
    assert fake.last_search_body["query_embedding"] == [1.0, 0.0, 0.0, 0.0]


def test_search_sources_empty_list_sends_empty():
    store, fake = _store()
    store.search("q", top_k=3, sources=[])
    assert fake.last_search_body["sources"] == []


def test_add_empty_chunks_returns_zero():
    store, fake = _store()
    assert store.add([]) == 0
    assert fake.chunks == []


def test_sources_returns_counts_grouped_by_source():
    store, fake = _store()
    a = chunk_sections("a.md", extract_file("a.md", b"alpha content here for testing"))
    b = chunk_sections("b.md", extract_file("b.md", b"bravo content here for testing"))
    store.add(a + b)
    got = {s["source"]: s["chunks"] for s in store.sources()}
    assert got["a.md"] == len(a)
    assert got["b.md"] == len(b)


def test_delete_missing_source_returns_zero():
    store, _ = _store()
    assert store.delete_source("ghost.md") == 0


def test_embedding_batch_inserts_every_row():
    store, fake = _store()
    chunks = []
    for i in range(7):
        chunks.extend(chunk_sections(f"f{i}.md", extract_file(f"f{i}.md", f"sample text number {i} for embedding".encode())))
    assert store.add(chunks) == len(chunks)
    assert len(fake.chunks) == len(chunks)
    assert all(c["embedding"] == [1.0, 0.0, 0.0, 0.0] for c in fake.chunks)
