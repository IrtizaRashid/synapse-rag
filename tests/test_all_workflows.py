import uuid
import pytest
from fastapi.testclient import TestClient
from app import app
from rag.auth import store as auth_store
from app import store as rag_store
from rag.chatbots import store as chatbot_store
from rag.workspace import store as workspace_store
from rag.llm import classify_intent, rewrite_query


@pytest.fixture
def client():
    return TestClient(app)


def test_intent_classification():
    assert classify_intent("Hi") == "SMALL_TALK"
    assert classify_intent("hello there!") == "SMALL_TALK"
    assert classify_intent("How are you?") == "SMALL_TALK"
    assert classify_intent("thanks") == "SMALL_TALK"
    assert classify_intent("What can this chatbot do?") == "META_QUESTION"
    assert classify_intent("Which documents do you have access to?") == "META_QUESTION"
    assert classify_intent("What is deadlock?") == "DOCUMENT_QUESTION"
    assert classify_intent("Explain section 5 of the contract") == "DOCUMENT_QUESTION"


def test_followup_query_rewriting():
    history = [
        {"role": "user", "content": "What is deadlock in operating systems?"},
        {"role": "assistant", "content": "Deadlock is a state where a set of processes are blocked..."}
    ]
    rewritten = rewrite_query("What are its conditions?", history)
    assert "deadlock" in rewritten.lower() or "conditions" in rewritten.lower()


def test_end_to_end_user_workflows(client):
    uid_a = uuid.uuid4().hex[:8]
    email_a = f"usera_{uid_a}@example.com"
    user_a = auth_store.create_user("User A", email_a, "Password123!")
    auth_store.mark_verified(email_a)
    
    res_login = client.post("/api/auth/login", json={"email": email_a, "password": "Password123!"})
    assert res_login.status_code == 200
    cookies_a = res_login.cookies

    # 2. Upload document OperatingSystems.txt for User A
    os_content = b"Operating Systems Notes: Deadlock occurs when four conditions hold simultaneously: Mutual Exclusion, Hold and Wait, No Preemption, and Circular Wait."
    res_upload_1 = client.post(
        "/api/ingest/files",
        files={"files": ("OperatingSystems.txt", os_content, "text/plain")},
        cookies=cookies_a
    )
    assert res_upload_1.status_code == 200

    # 3. Create Chatbot A assigned to OperatingSystems.txt
    res_bot_a = client.post(
        "/api/chatbots",
        json={
            "name": "OS Assistant",
            "description": "Answers OS questions",
            "sources": ["OperatingSystems.txt"]
        },
        cookies=cookies_a
    )
    assert res_bot_a.status_code == 200
    bot_a = res_bot_a.json()["chatbot"]
    bot_a_id = str(bot_a["id"])

    # 4. Create Conversation for User A
    res_conv_a = client.post(
        "/api/conversations",
        json={"title": "New conversation", "bot_ids": [bot_a_id]},
        cookies=cookies_a
    )
    assert res_conv_a.status_code == 200
    conv_a_id = res_conv_a.json()["conversation"]["id"]

    # Test 4a: Send greeting "Hi" -> Natural greeting
    res_msg_hi = client.post(
        f"/api/conversations/{conv_a_id}/messages",
        json={"content": "Hi", "bot_ids": [bot_a_id]},
        cookies=cookies_a
    )
    assert res_msg_hi.status_code == 200
    ans_hi = res_msg_hi.json()["responses"][0]["answer"]
    assert "Hi!" in ans_hi or "assistant" in ans_hi.lower() or "help" in ans_hi.lower()

    # Test 4b: Ask document question "What is deadlock?" -> Grounded answer
    res_msg_doc = client.post(
        f"/api/conversations/{conv_a_id}/messages",
        json={"content": "What is deadlock?", "bot_ids": [bot_a_id]},
        cookies=cookies_a
    )
    assert res_msg_doc.status_code == 200
    resp_doc = res_msg_doc.json()["responses"][0]
    assert len(resp_doc["sources"]) > 0 or "deadlock" in resp_doc["answer"].lower()

    # Test 4c: Ask outside question "Who won the latest football match?" -> Refusal
    res_msg_out = client.post(
        f"/api/conversations/{conv_a_id}/messages",
        json={"content": "Who won the latest football match?", "bot_ids": [bot_a_id]},
        cookies=cookies_a
    )
    assert res_msg_out.status_code == 200
    ans_out = res_msg_out.json()["responses"][0]["answer"]
    assert "couldn't find information" in ans_out.lower() or "not available" in ans_out.lower()

    # 5. Upload Database.txt & Create Database Assistant
    db_content = b"Database Notes: Normalization is the process of organizing data to reduce redundancy."
    client.post(
        "/api/ingest/files",
        files={"files": ("Database.txt", db_content, "text/plain")},
        cookies=cookies_a
    )
    res_bot_db = client.post(
        "/api/chatbots",
        json={"name": "Database Assistant", "sources": ["Database.txt"]},
        cookies=cookies_a
    )
    bot_db_id = str(res_bot_db.json()["chatbot"]["id"])

    res_conv_db = client.post(
        "/api/conversations",
        json={"title": "DB chat", "bot_ids": [bot_db_id]},
        cookies=cookies_a
    )
    conv_db_id = res_conv_db.json()["conversation"]["id"]

    # Test Document Isolation: Ask Database Assistant something from OperatingSystems.txt
    res_iso = client.post(
        f"/api/conversations/{conv_db_id}/messages",
        json={"content": "What is deadlock?", "bot_ids": [bot_db_id]},
        cookies=cookies_a
    )
    ans_iso = res_iso.json()["responses"][0]["answer"]
    assert "couldn't find information" in ans_iso.lower() or "not available" in ans_iso.lower()

    # Test Chatbot with 0 documents assigned
    res_bot_empty = client.post(
        "/api/chatbots",
        json={"name": "Empty Bot", "sources": []},
        cookies=cookies_a
    )
    bot_empty_id = str(res_bot_empty.json()["chatbot"]["id"])
    res_conv_empty = client.post(
        "/api/conversations",
        json={"title": "Empty Chat", "bot_ids": [bot_empty_id]},
        cookies=cookies_a
    )
    conv_empty_id = res_conv_empty.json()["conversation"]["id"]

    res_empty_ask = client.post(
        f"/api/conversations/{conv_empty_id}/messages",
        json={"content": "Explain normalization", "bot_ids": [bot_empty_id]},
        cookies=cookies_a
    )
    ans_empty = res_empty_ask.json()["responses"][0]["answer"]
    assert "doesn't currently have any documents assigned" in ans_empty

    # Test Tenant Isolation: User B cannot access User A's conversation or chatbot
    uid_b = uuid.uuid4().hex[:8]
    email_b = f"userb_{uid_b}@example.com"
    user_b = auth_store.create_user("User B", email_b, "Password123!")
    auth_store.mark_verified(email_b)
    res_login_b = client.post("/api/auth/login", json={"email": email_b, "password": "Password123!"})
    cookies_b = res_login_b.cookies

    res_hack = client.get(f"/api/conversations/{conv_a_id}", cookies=cookies_b)
    assert res_hack.status_code == 404
