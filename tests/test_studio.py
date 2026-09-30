import uuid
from fastapi.testclient import TestClient
from app import app
from rag.auth import store as auth_store
from rag.llm import retrieval_answer, rewrite_query


def test_independent_question_does_not_inherit_topic():
    assert rewrite_query("Who won the latest football match?", [{"role": "user", "content": "What is deadlock?"}]) == "Who won the latest football match?"


def test_retrieval_fallback_is_client_friendly():
    answer, provider = retrieval_answer(
        "What production architecture does Synapse RAG use?",
        [{
            "source": "client.md",
            "location": "document text",
            "text": "The production architecture uses Next.js, FastAPI, Supabase pgvector, and Gemini.",
        }],
    )
    assert provider == "retrieval-only"
    assert "generator is not available" not in answer.lower()
    assert "assigned sources" in answer
    assert "Next.js" in answer
    assert "Gemini could not" not in answer


def test_retrieval_is_private_and_returns_passages():
    with TestClient(app) as client:
        assert client.get("/api/workspace/status").status_code == 401
        name = uuid.uuid4().hex
        email = f"studio-{name}@example.com"
        auth_store.create_user("Studio Tester", email, "Password123!")
        auth_store.mark_verified(email)
        assert client.post("/api/auth/login", json={"email":email,"password":"Password123!"}).status_code == 200
        status = client.get("/api/workspace/status")
        assert status.status_code == 200
        assert set(status.json()) == {"database", "retrieval", "generation", "max_upload_mb"}
        response = client.post("/api/ingest/files", files={"files":("studio.txt",b"The observatory telescope is calibrated every Friday.","text/plain")})
        assert response.json()["results"][0]["status"] == "queued"
        result = client.post("/api/retrieval/test",json={"question":"When is the telescope calibrated?","top_k":3})
        assert result.status_code == 200
        assert "Friday" in result.json()["sources"][0]["preview"]
        client.post("/api/auth/logout")
        assert client.post("/api/retrieval/test",json={"question":"telescope"}).status_code == 401
