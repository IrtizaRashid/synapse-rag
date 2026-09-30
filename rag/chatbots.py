"""Chatbot registry.

Each chatbot is a named assistant bound to a set of ingested file sources.
Stored in a Supabase Postgres table (``public.chatbots``) via REST when
Supabase credentials exist, otherwise in a local JSON file so the app still
works in zero-config mode.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

import httpx

log = logging.getLogger("rag.chatbots")


class LocalChatbotStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self._rows: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._rows = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._rows = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._rows, indent=2), encoding="utf-8")

    def list(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self._rows]

    def create(self, name: str, description: str, sources: list[str], owner_id: int) -> dict:
        row = {
            "id": str(uuid.uuid4()),
            "name": name,
            "description": description,
            "sources": sorted(sources),
            "owner_id": owner_id,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        with self.lock:
            self._rows.append(row)
            self._save()
        return dict(row)

    def update(self, chatbot_id: str, name: str | None, description: str | None, sources: list[str] | None) -> dict | None:
        with self.lock:
            for row in self._rows:
                if row["id"] == chatbot_id:
                    if name is not None:
                        row["name"] = name
                    if description is not None:
                        row["description"] = description
                    if sources is not None:
                        row["sources"] = sorted(sources)
                    row["updated_at"] = time.time()
                    self._save()
                    return dict(row)
        return None

    def delete(self, chatbot_id: str) -> bool:
        with self.lock:
            before = len(self._rows)
            self._rows = [r for r in self._rows if r["id"] != chatbot_id]
            if len(self._rows) != before:
                self._save()
                return True
        return False


class SupabaseChatbotStore:
    def __init__(self, url: str, anon_key: str, service_role_key: str, client: httpx.Client | None = None):
        self.base = url.rstrip("/")
        self._anon = anon_key
        self._service = service_role_key
        self._client = client or httpx.Client(timeout=30)

    def _headers(self, prefer: str = "return=minimal") -> dict:
        return {
            "apikey": self._anon,
            "Authorization": f"Bearer {self._service}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        }

    def _table(self) -> str:
        return f"{self.base}/rest/v1/chatbots"

    def _check(self, response: httpx.Response, context: str) -> httpx.Response:
        if response.status_code >= 400:
            raise RuntimeError(f"{context} failed ({response.status_code}): {response.text[:300]}")
        return response

    def list(self) -> list[dict]:
        r = self._check(self._client.get(self._table(), params={"select": "*"}, headers=self._headers()), "list chatbots")
        return r.json()

    def create(self, name: str, description: str, sources: list[str], owner_id: int) -> dict:
        payload = {"name": name, "description": description, "sources": sorted(sources), "owner_id": owner_id}
        r = self._check(
            self._client.post(self._table(), json=payload, headers=self._headers("return=representation")),
            "create chatbot",
        )
        rows = r.json()
        if not rows:
            raise RuntimeError("create chatbot returned no row")
        return rows[0]

    def update(self, chatbot_id: str, name: str | None, description: str | None, sources: list[str] | None) -> dict | None:
        payload: dict = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if sources is not None:
            payload["sources"] = sorted(sources)
        if not payload:
            return None
        r = self._check(
            self._client.patch(
                self._table(),
                params={"id": f"eq.{chatbot_id}"},
                json=payload,
                headers=self._headers("return=representation"),
            ),
            "update chatbot",
        )
        rows = r.json()
        return rows[0] if rows else None

    def delete(self, chatbot_id: str) -> bool:
        r = self._check(
            self._client.delete(self._table(), params={"id": f"eq.{chatbot_id}"}, headers=self._headers()),
            "delete chatbot",
        )
        return True


def _build_chatbot_store():
    backend = __import__("os").getenv("CHATBOT_BACKEND", "").strip().lower()
    url = __import__("os").getenv("SUPABASE_URL", "").strip()
    anon = __import__("os").getenv("SUPABASE_ANON_KEY", "").strip()
    service = __import__("os").getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if backend != "local" and url and anon and service:
        log.info("Chatbot store: Supabase Postgres")
        return SupabaseChatbotStore(url, anon, service)
    default_path = Path(__file__).resolve().parent.parent / "data" / "chatbots.json"
    path = Path(__import__("os").getenv("CHATBOT_DB_PATH", str(default_path)))
    log.info("Chatbot store: local JSON (%s)", path)
    return LocalChatbotStore(path)


store = _build_chatbot_store()
