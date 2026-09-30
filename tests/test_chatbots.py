import os
import uuid
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import app, store

client = TestClient(app)
PASSWORD = "StrongPass1!"


def _unique_email() -> str:
    return f"bot{uuid.uuid4().hex[:10]}@example.com"


def auth_client() -> TestClient:
    c = TestClient(app)
    email = _unique_email()
    r = c.post("/api/auth/signup", json={"name": "Bot Tester", "email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    code = r.json().get("dev_code")
    assert code
    assert c.post("/api/auth/otp/verify", json={"email": email, "purpose": "signup", "code": code}).status_code == 200
    assert c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return c


def add_source(c: TestClient, name: str = "bot-src.md", text: str = "The falcon project launches in June.") -> str:
    assert c.post("/api/ingest/files", files=[("files", (name, text.encode(), "text/markdown"))]).status_code == 200
    return name


def _cleanup(c: TestClient, chatbots: list[str] | None = None, sources: list[str] | None = None):
    for cid in chatbots or []:
        c.delete(f"/api/chatbots/{cid}")
    for s in sources or []:
        c.post("/api/documents/delete", json={"source": s})


def test_chatbot_requires_auth():
    assert client.get("/api/chatbots").status_code == 401
    assert client.post("/api/chatbots", json={"name": "x", "sources": []}).status_code == 401


def test_create_chatbot_binds_sources():
    c = auth_client()
    src = add_source(c)
    r = c.post("/api/chatbots", json={"name": "Falcon Bot", "description": "knows falcon", "sources": [src]})
    assert r.status_code == 200, r.text
    bot = r.json()["chatbot"]
    assert bot["name"] == "Falcon Bot"
    assert bot["sources"] == [src]
    assert bot["id"]
    _cleanup(c, chatbots=[bot["id"]], sources=[src])


def test_create_chatbot_rejects_unknown_source():
    c = auth_client()
    r = c.post("/api/chatbots", json={"name": "X", "sources": ["nope.md"]})
    assert r.status_code == 400
    assert "Unknown sources" in r.json()["detail"]


def test_create_chatbot_requires_name():
    c = auth_client()
    src = add_source(c)
    r = c.post("/api/chatbots", json={"name": " ", "sources": [src]})
    assert r.status_code == 422
    _cleanup(c, sources=[src])


def test_list_chatbots():
    c = auth_client()
    src = add_source(c)
    names = ["Alpha", "Beta", "Gamma"]
    ids = []
    for n in names:
        r = c.post("/api/chatbots", json={"name": n, "sources": [src]})
        ids.append(r.json()["chatbot"]["id"])
    r = c.get("/api/chatbots")
    assert r.status_code == 200
    got = {b["name"] for b in r.json()["chatbots"]}
    assert got == set(names)
    _cleanup(c, chatbots=ids, sources=[src])


def test_update_chatbot_name_and_sources():
    c = auth_client()
    src = add_source(c, name="a.md")
    src2 = add_source(c, name="b.md")
    bot = c.post("/api/chatbots", json={"name": "Old", "sources": [src]}).json()["chatbot"]
    r = c.patch(f"/api/chatbots/{bot['id']}", json={"name": "New", "sources": [src2]})
    assert r.status_code == 200, r.text
    updated = r.json()["chatbot"]
    assert updated["name"] == "New"
    assert updated["sources"] == [src2]
    _cleanup(c, chatbots=[bot["id"]], sources=[src, src2])


def test_update_chatbot_not_found():
    c = auth_client()
    r = c.patch("/api/chatbots/does-not-exist", json={"name": "X"})
    assert r.status_code == 404


def test_update_chatbot_unknown_source_rejected():
    c = auth_client()
    src = add_source(c)
    bot = c.post("/api/chatbots", json={"name": "B", "sources": [src]}).json()["chatbot"]
    r = c.patch(f"/api/chatbots/{bot['id']}", json={"sources": ["ghost.md"]})
    assert r.status_code == 400
    _cleanup(c, chatbots=[bot["id"]], sources=[src])


def test_delete_chatbot():
    c = auth_client()
    src = add_source(c)
    bot = c.post("/api/chatbots", json={"name": "Tmp", "sources": [src]}).json()["chatbot"]
    assert c.delete(f"/api/chatbots/{bot['id']}").status_code == 200
    assert c.delete(f"/api/chatbots/{bot['id']}").status_code == 404
    _cleanup(c, sources=[src])


def test_ask_with_chatbot_restricts_to_its_files():
    c = auth_client()
    src = add_source(c, name="chosen.md", text="The zebra project uses green approval.")
    other = add_source(c, name="other.md", text="The parrot project uses red confidential procedure.")
    bot = c.post("/api/chatbots", json={"name": "Zebra Bot", "sources": [src]}).json()["chatbot"]
    r = c.post("/api/ask", json={"question": "What color does the zebra project use?", "chatbot_id": bot["id"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["chatbot"]["id"] == bot["id"]
    assert data["selected_sources"] == [src]
    assert data["sources"]
    assert all(item["source"] == src for item in data["sources"])
    assert "other.md" not in data["answer"]
    _cleanup(c, chatbots=[bot["id"]], sources=[src, other])


def test_ask_with_unknown_chatbot_404():
    c = auth_client()
    r = c.post("/api/ask", json={"question": "hello there", "chatbot_id": "missing-bot"})
    assert r.status_code == 404


def test_chatbot_survives_source_deletion():
    c = auth_client()
    src = add_source(c)
    bot = c.post("/api/chatbots", json={"name": "Persist", "sources": [src]}).json()["chatbot"]
    assert c.post("/api/documents/delete", json={"source": src}).status_code == 200
    r = c.post("/api/ask", json={"question": "anything at all?", "chatbot_id": bot["id"]})
    assert r.status_code == 200
    _cleanup(c, chatbots=[bot["id"]])


def test_ask_refuses_out_of_scope_question():
    c = auth_client()
    src = add_source(c, name="finance.md", text="Quarterly revenue grew 23 percent.")
    bot = c.post("/api/chatbots", json={"name": "Finance Bot", "sources": [src]}).json()["chatbot"]
    r = c.post("/api/ask", json={"question": "Who is the president of France?", "chatbot_id": bot["id"]})
    assert r.status_code == 200
    data = r.json()
    assert "only answer questions" in data["answer"].lower() or "could not find" in data["answer"].lower() \
        or "not contain" in data["answer"].lower() or "outside" in data["answer"].lower()
    _cleanup(c, chatbots=[bot["id"]], sources=[src])


def test_chatbot_api_key_access():
    c = TestClient(app)
    c.headers.update({"X-API-Key": "test-api-key"})
    r = c.get("/api/chatbots")
    assert r.status_code == 200
    assert "chatbots" in r.json()


def test_extended_bot_profile_and_multi_bot_conversation_stream(monkeypatch):
    c = auth_client()
    src = add_source(c, name=f"team-{uuid.uuid4().hex[:6]}.md", text="Project Aurora has a verified blue status.")
    ids = []
    for name, avatar in [("Research Agent", "✦"), ("Data Analyst", "Σ")]:
        response = c.post("/api/chatbots", json={
            "name": name, "description": "Specialist", "sources": [src],
            "avatar": avatar, "instructions": f"Respond as {name}", "enabled": True,
        })
        assert response.status_code == 200, response.text
        bot = response.json()["chatbot"]
        assert bot["avatar"] == avatar
        assert bot["instructions"] == f"Respond as {name}"
        ids.append(str(bot["id"]))

    monkeypatch.setattr("app.answer_with_sources", lambda question, results, chatbot_name=None, **kwargs:
                        (f"{chatbot_name} verified Aurora from sources [1].", "test"))
    created = c.post("/api/conversations", json={"bot_ids": ids}).json()["conversation"]
    streamed = c.post(f"/api/conversations/{created['id']}/messages/stream", json={
        "content": "What is Aurora's status?", "bot_ids": ids, "attachments": [src],
    })
    assert streamed.status_code == 200, streamed.text
    events = [json.loads(line) for line in streamed.text.splitlines() if line.strip()]
    assert events[0]["type"] == "user"
    assistants = [event for event in events if event["type"] == "assistant"]
    assert len(assistants) == 2
    assert {event["message"]["bot_name"] for event in assistants} == {"Research Agent", "Data Analyst"}
    assert events[-1]["type"] == "done"

    saved = c.get(f"/api/conversations/{created['id']}").json()["conversation"]
    assert len(saved["messages"]) == 3
    assert c.patch(f"/api/conversations/{created['id']}", json={"title": "Aurora review"}).status_code == 200
    assert c.delete(f"/api/conversations/{created['id']}").status_code == 200
    _cleanup(c, chatbots=ids, sources=[src])


def test_regenerate_message_must_belong_to_conversation(monkeypatch):
    c = auth_client()
    src = add_source(c, name=f"regen-{uuid.uuid4().hex[:6]}.md", text="Regeneration source says the window opens at noon.")
    bot = c.post("/api/chatbots", json={"name": "Regen Bot", "sources": [src]}).json()["chatbot"]
    monkeypatch.setattr(
        "app.answer_with_sources",
        lambda question, results, chatbot_name=None, **kwargs: ("The window opens at noon [1].", "test"),
    )
    first = c.post("/api/conversations", json={"bot_ids": [str(bot["id"])]}).json()["conversation"]
    second = c.post("/api/conversations", json={"bot_ids": [str(bot["id"])]}).json()["conversation"]
    sent = c.post(
        f"/api/conversations/{first['id']}/messages",
        json={"content": "When does the window open?", "bot_ids": [str(bot["id"])]},
    )
    assert sent.status_code == 200, sent.text
    assistant_id = sent.json()["responses"][0]["message"]["id"]

    wrong_thread = c.post(f"/api/conversations/{second['id']}/messages/{assistant_id}/regenerate")
    assert wrong_thread.status_code == 404
    _cleanup(c, chatbots=[str(bot["id"])], sources=[src])


def test_file_manager_preview_rename_and_fast_delete():
    c = auth_client()
    original = f"manager-{uuid.uuid4().hex[:6]}.py"
    renamed = original.replace("manager-", "renamed-")
    uploaded = c.post("/api/ingest/files", files=[
        ("files", (original, b"def calculate_total(values):\n    return sum(values)\n", "text/x-python"))
    ])
    assert uploaded.status_code == 200, uploaded.text
    result = uploaded.json()["results"][0]
    assert result["status"] == "queued"
    file_id = result["file_id"]

    preview = c.get(f"/api/files/{file_id}/preview")
    assert preview.status_code == 200
    assert "calculate_total" in preview.json()["content"]

    changed = c.patch(f"/api/files/{file_id}", json={"name": renamed})
    assert changed.status_code == 200, changed.text
    assert changed.json()["file"]["source"] == renamed

    deleted = c.delete(f"/api/files/{file_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["removed_chunks"] >= 1
    assert c.get(f"/api/files/{file_id}/preview").status_code == 404
