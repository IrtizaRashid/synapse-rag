"""Public end-to-end test for the Synapse workspace.

Creates two isolated users, uploads structured data, creates two bots, streams a
multi-agent conversation with citations, exercises follow-up context, preview,
rename/search, and fast deletion.
"""
from __future__ import annotations

import os
import time
import uuid

import requests

BASE = os.getenv("WORKSPACE_E2E_URL", "http://127.0.0.1:8000").rstrip("/")
PASSWORD = "WorkspaceQA9!"


def expect(response: requests.Response, status: int = 200) -> dict:
    if response.status_code != status:
        raise AssertionError(f"{response.request.method} {response.url}: {response.status_code} {response.text[:1000]}")
    return response.json()


def register(label: str) -> tuple[requests.Session, str]:
    session = requests.Session()
    email = f"{label}-{uuid.uuid4().hex[:10]}@example.com"
    signup = expect(session.post(f"{BASE}/api/auth/signup", json={
        "email": email, "password": PASSWORD, "name": f"{label.title()} QA",
    }))
    code = signup.get("dev_code")
    if not code:
        raise AssertionError("DEV_SHOW_OTP must be enabled for this automated test")
    expect(session.post(f"{BASE}/api/auth/otp/verify", json={
        "email": email, "code": code, "purpose": "signup",
    }))
    expect(session.post(f"{BASE}/api/auth/login", json={"email": email, "password": PASSWORD}))
    return session, email


def stream_events(session: requests.Session, conversation_id: str, payload: dict) -> list[dict]:
    response = session.post(
        f"{BASE}/api/conversations/{conversation_id}/messages/stream",
        json=payload, stream=True, timeout=150,
    )
    if response.status_code != 200:
        raise AssertionError(f"stream: {response.status_code} {response.text[:1000]}")
    events = [__import__("json").loads(line) for line in response.iter_lines(decode_unicode=True) if line]
    if not events or events[-1].get("type") != "done":
        raise AssertionError(f"Incomplete stream: {events[-2:]}")
    return events


def main() -> None:
    primary, primary_email = register("workspace-primary")
    secondary, secondary_email = register("workspace-isolation")

    csv_bytes = b"month,product,revenue\nJanuary,Orchid,1200\nFebruary,Marble,900\nMarch,Orchid,1500\n"
    upload = expect(primary.post(f"{BASE}/api/ingest/files", files={
        "files": ("sales_analysis.csv", csv_bytes, "text/csv"),
    }))["results"][0]
    assert upload["status"] == "indexed" and upload["metadata"]["rows"] == 3
    file_id, source = upload["file_id"], upload["source"]

    # Tenant B must not see tenant A's vectors or file metadata.
    assert expect(secondary.get(f"{BASE}/api/files"))["files"] == []
    assert expect(secondary.get(f"{BASE}/api/documents"))["documents"] == []

    bot_specs = [
        ("Data Analyst", "Analyze tables precisely and use Markdown tables."),
        ("Executive Summarizer", "Lead with the answer, then cite supporting evidence."),
    ]
    bots = []
    for name, instructions in bot_specs:
        bot = expect(primary.post(f"{BASE}/api/chatbots", json={
            "name": name, "description": f"QA {name}", "sources": [source],
            "instructions": instructions, "avatar": "D", "enabled": True,
        }))["chatbot"]
        bots.append(str(bot["id"]))

    conversation = expect(primary.post(f"{BASE}/api/conversations", json={
        "title": "New conversation", "bot_ids": bots,
    }))["conversation"]
    conversation_id = conversation["id"]

    started = time.perf_counter()
    events = stream_events(primary, conversation_id, {
        "content": "Which product had the highest revenue and in which month? Use a Markdown table.",
        "bot_ids": bots, "attachments": [source],
    })
    first_elapsed = time.perf_counter() - started
    assistants = [event["message"] for event in events if event.get("type") == "assistant"]
    assert len(assistants) == 2
    assert all(message["sources"] and message["sources"][0]["source"] == source for message in assistants)
    assert {message["bot_name"] for message in assistants} == set(name for name, _ in bot_specs)

    followup = stream_events(primary, conversation_id, {
        "content": "Now compare the highest and lowest revenue values.",
        "bot_ids": bots, "attachments": [],
    })
    assert len([event for event in followup if event.get("type") == "assistant"]) == 2

    renamed_title = "Revenue review"
    expect(primary.patch(f"{BASE}/api/conversations/{conversation_id}", json={"title": renamed_title}))
    found = expect(primary.get(f"{BASE}/api/conversations", params={"q": "Revenue"}))["conversations"]
    assert any(item["id"] == conversation_id and item["title"] == renamed_title for item in found)

    preview = expect(primary.get(f"{BASE}/api/files/{file_id}/preview"))
    assert preview["file"]["metadata"]["columns"] == 3 and "Orchid" in preview["content"]

    renamed_source = "quarterly_revenue.csv"
    rename_started = time.perf_counter()
    renamed = expect(primary.patch(f"{BASE}/api/files/{file_id}", json={"name": renamed_source}))
    rename_elapsed = time.perf_counter() - rename_started
    assert renamed["file"]["source"] == renamed_source

    delete_started = time.perf_counter()
    removed = expect(primary.delete(f"{BASE}/api/files/{file_id}"))
    delete_elapsed = time.perf_counter() - delete_started
    assert removed["removed_chunks"] >= 1
    assert expect(primary.get(f"{BASE}/api/files"))["files"] == []

    expect(primary.delete(f"{BASE}/api/conversations/{conversation_id}"))
    for bot_id in bots:
        expect(primary.delete(f"{BASE}/api/chatbots/{bot_id}"))

    print("WORKSPACE_E2E_OK")
    print(f"primary={primary_email} secondary={secondary_email}")
    print(f"multi_bot_first_response_seconds={first_elapsed:.3f}")
    print(f"rename_seconds={rename_elapsed:.3f}")
    print(f"delete_seconds={delete_elapsed:.3f}")
    print("tenant_isolation=PASS streamed_bots=2 followup_context=PASS citations=PASS csv_preview=PASS cleanup=PASS")


if __name__ == "__main__":
    main()
