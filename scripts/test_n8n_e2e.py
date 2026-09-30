from __future__ import annotations

import base64
import json
import sys
from typing import Any

import requests

N8N = "http://127.0.0.1:5678/webhook/rag"
TIMEOUT = 240


def post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{N8N}/{path}", json=payload, timeout=TIMEOUT)
    print(f"{path}: HTTP {response.status_code}", flush=True)
    if not response.ok:
        print(response.text)
        response.raise_for_status()
    return response.json()


def upload(filename: str, text: str) -> dict[str, Any]:
    return post(
        "upload",
        {
            "filename": filename,
            "mime_type": "text/markdown",
            "content_base64": base64.b64encode(text.encode()).decode(),
        },
    )


def main() -> int:
    selected = "e2e-selected.md"
    excluded = "e2e-excluded.md"
    upload(selected, "# Project Atlas\nThe verified Project Atlas launch codeword is ORCHID.")
    upload(excluded, "# Project Atlas\nThe obsolete and confidential Project Atlas codeword is MARBLE.")

    chatbot = post(
        "chatbot",
        {
            "name": "E2E Selected Sources Bot",
            "description": "Automated end-to-end verification bot",
            "sources": [selected],
        },
    )
    chatbot_id = chatbot.get("id") or chatbot.get("chatbot_id")
    if not chatbot_id and isinstance(chatbot.get("chatbot"), dict):
        chatbot_id = chatbot["chatbot"].get("id")
    if not chatbot_id:
        raise AssertionError(f"No chatbot ID in response: {chatbot}")

    answer = post(
        "ask",
        {
            "chatbot_id": chatbot_id,
            "question": "What is the verified Project Atlas launch codeword?",
            "top_k": 5,
        },
    )
    sources = answer.get("sources", [])
    source_names = {item.get("source") for item in sources}
    text = str(answer.get("answer", ""))
    assert sources, f"No sources returned: {answer}"
    assert source_names == {selected}, f"Unselected source leaked into retrieval: {source_names}"
    assert "ORCHID" in text.upper(), f"Expected selected-file answer not found: {text}"
    assert "MARBLE" not in text.upper(), f"Unselected content leaked into answer: {text}"

    print(json.dumps({
        "result": "PASS",
        "chatbot_id": chatbot_id,
        "selected_sources": sorted(source_names),
        "excluded_source": excluded,
        "answer": text,
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"E2E FAILED: {exc}", file=sys.stderr)
        raise
