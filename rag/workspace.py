"""Persistent workspace data for conversations, messages, files, and bot profiles.

The vector database remains responsible for semantic chunks. This SQLite store
keeps fast product/workspace metadata and works identically with local or
Supabase RAG backends.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("WORKSPACE_DB_PATH", str(BASE / "data" / "workspace.db")))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE / "data" / "uploads")))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class WorkspaceStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    name TEXT NOT NULL,
                    extension TEXT NOT NULL DEFAULT '',
                    mime_type TEXT NOT NULL DEFAULT '',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'ready',
                    chunks INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    preview TEXT NOT NULL DEFAULT '',
                    stored_path TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(owner_id, source)
                );
                CREATE INDEX IF NOT EXISTS files_owner_updated_idx
                    ON files(owner_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS files_owner_type_idx
                    ON files(owner_id, extension);

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    bot_ids_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS conversations_owner_updated_idx
                    ON conversations(owner_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    owner_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    bot_id TEXT,
                    bot_name TEXT,
                    content TEXT NOT NULL,
                    sources_json TEXT NOT NULL DEFAULT '[]',
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    state TEXT NOT NULL DEFAULT 'completed',
                    created_at REAL NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS messages_conversation_created_idx
                    ON messages(conversation_id, created_at);

                CREATE TABLE IF NOT EXISTS bot_profiles (
                    chatbot_id TEXT PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    avatar TEXT NOT NULL DEFAULT 'sparkles',
                    instructions TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    color TEXT NOT NULL DEFAULT '#6d5dfc',
                    updated_at REAL NOT NULL
                );
                """
            )
            self._db.commit()

    @staticmethod
    def _file(row: sqlite3.Row | dict) -> dict:
        item = dict(row)
        item["metadata"] = _loads(item.pop("metadata_json", "{}"), {})
        return item

    @staticmethod
    def _conversation(row: sqlite3.Row | dict) -> dict:
        item = dict(row)
        item["bot_ids"] = _loads(item.pop("bot_ids_json", "[]"), [])
        return item

    @staticmethod
    def _message(row: sqlite3.Row | dict) -> dict:
        item = dict(row)
        item["sources"] = _loads(item.pop("sources_json", "[]"), [])
        item["attachments"] = _loads(item.pop("attachments_json", "[]"), [])
        return item

    def save_upload(self, file_id: str, filename: str, data: bytes) -> str:
        safe_ext = Path(filename).suffix.lower()[:12]
        target = UPLOAD_DIR / f"{file_id}{safe_ext}"
        target.write_bytes(data)
        return str(target)

    def upsert_file(
        self,
        owner_id: int,
        source: str,
        *,
        name: str | None = None,
        mime_type: str = "",
        size_bytes: int = 0,
        status: str = "ready",
        chunks: int = 0,
        metadata: dict | None = None,
        preview: str = "",
        stored_path: str = "",
    ) -> dict:
        now = time.time()
        file_id = str(uuid.uuid4())
        display = name or source
        extension = Path(display).suffix.lower()
        with self._lock:
            existing = self._db.execute(
                "SELECT id, created_at, stored_path FROM files WHERE owner_id=? AND source=?",
                (owner_id, source),
            ).fetchone()
            if existing:
                file_id = existing["id"]
                if not stored_path:
                    stored_path = existing["stored_path"]
                self._db.execute(
                    """UPDATE files SET name=?,extension=?,mime_type=?,size_bytes=?,status=?,chunks=?,
                       metadata_json=?,preview=?,stored_path=?,updated_at=? WHERE id=?""",
                    (display, extension, mime_type, size_bytes, status, chunks, _json(metadata or {}),
                     preview[:200_000], stored_path, now, file_id),
                )
            else:
                self._db.execute(
                    """INSERT INTO files
                       (id,owner_id,source,name,extension,mime_type,size_bytes,status,chunks,metadata_json,
                        preview,stored_path,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (file_id, owner_id, source, display, extension, mime_type, size_bytes, status, chunks,
                     _json(metadata or {}), preview[:200_000], stored_path, now, now),
                )
            self._db.commit()
            row = self._db.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        return self._file(row)

    def list_files(self, owner_id: int, query: str = "", extension: str = "", sort: str = "newest") -> list[dict]:
        clauses = ["owner_id=?"]
        params: list[Any] = [owner_id]
        if query:
            clauses.append("(lower(name) LIKE ? OR lower(source) LIKE ?)")
            needle = f"%{query.lower()}%"
            params.extend([needle, needle])
        if extension:
            clauses.append("extension=?")
            params.append(extension.lower() if extension.startswith(".") else "." + extension.lower())
        order = {
            "oldest": "created_at ASC",
            "name": "lower(name) ASC",
            "size": "size_bytes DESC",
            "newest": "updated_at DESC",
        }.get(sort, "updated_at DESC")
        with self._lock:
            rows = self._db.execute(
                f"SELECT * FROM files WHERE {' AND '.join(clauses)} ORDER BY {order}", params
            ).fetchall()
        return [self._file(row) for row in rows]

    def get_file(self, owner_id: int, file_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM files WHERE id=? AND owner_id=?", (file_id, owner_id)).fetchone()
        return self._file(row) if row else None

    def get_file_by_source(self, owner_id: int, source: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM files WHERE source=? AND owner_id=?", (source, owner_id)).fetchone()
        return self._file(row) if row else None

    def rename_file(self, owner_id: int, file_id: str, new_name: str, new_source: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM files WHERE id=? AND owner_id=?", (file_id, owner_id)).fetchone()
            if not row:
                return None
            self._db.execute(
                "UPDATE files SET name=?,source=?,extension=?,updated_at=? WHERE id=?",
                (new_name, new_source, Path(new_name).suffix.lower(), time.time(), file_id),
            )
            self._db.commit()
            updated = self._db.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        return self._file(updated)

    def delete_file(self, owner_id: int, file_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM files WHERE id=? AND owner_id=?", (file_id, owner_id)).fetchone()
            if not row:
                return None
            self._db.execute("DELETE FROM files WHERE id=?", (file_id,))
            self._db.commit()
        item = self._file(row)
        path = item.get("stored_path")
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        return item

    def sync_sources(self, owner_id: int, sources: list[dict]) -> list[dict]:
        available = {src["source"] for src in sources}
        for src in sources:
            if not self.get_file_by_source(owner_id, src["source"]):
                self.upsert_file(owner_id, src["source"], chunks=int(src.get("chunks", 0)))
            else:
                with self._lock:
                    self._db.execute(
                        "UPDATE files SET chunks=?,status=CASE WHEN status='processing' THEN status ELSE 'ready' END WHERE owner_id=? AND source=?",
                        (int(src.get("chunks", 0)), owner_id, src["source"]),
                    )
                    self._db.commit()
        # Remove stale ready metadata after a vector source was deleted. Keep
        # processing/error rows so failed uploads remain visible to the user.
        for item in self.list_files(owner_id):
            if item["status"] == "ready" and item["source"] not in available:
                self.delete_file(owner_id, item["id"])
        return self.list_files(owner_id)

    def create_conversation(self, owner_id: int, title: str = "New conversation", bot_ids: list[str] | None = None) -> dict:
        now = time.time()
        row = {"id": str(uuid.uuid4()), "owner_id": owner_id, "title": title.strip() or "New conversation",
               "bot_ids_json": _json(bot_ids or []), "created_at": now, "updated_at": now}
        with self._lock:
            self._db.execute(
                "INSERT INTO conversations(id,owner_id,title,bot_ids_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                tuple(row.values()),
            )
            self._db.commit()
        return self._conversation(row)

    def list_conversations(self, owner_id: int, query: str = "") -> list[dict]:
        sql = "SELECT c.*, (SELECT content FROM messages m WHERE m.conversation_id=c.id ORDER BY created_at DESC LIMIT 1) AS preview FROM conversations c WHERE owner_id=?"
        params: list[Any] = [owner_id]
        if query:
            sql += " AND (lower(title) LIKE ? OR EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id=c.id AND lower(m.content) LIKE ?))"
            needle = f"%{query.lower()}%"
            params.extend([needle, needle])
        sql += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return [self._conversation(row) for row in rows]

    def get_conversation(self, owner_id: int, conversation_id: str, include_messages: bool = True) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM conversations WHERE id=? AND owner_id=?", (conversation_id, owner_id)
            ).fetchone()
            if not row:
                return None
            item = self._conversation(row)
            if include_messages:
                messages = self._db.execute(
                    "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at,id", (conversation_id,)
                ).fetchall()
                item["messages"] = [self._message(message) for message in messages]
        return item

    def update_conversation(self, owner_id: int, conversation_id: str, *, title: str | None = None,
                            bot_ids: list[str] | None = None) -> dict | None:
        updates, params = [], []
        if title is not None:
            updates.append("title=?")
            params.append(title.strip()[:120] or "New conversation")
        if bot_ids is not None:
            updates.append("bot_ids_json=?")
            params.append(_json(bot_ids))
        if not updates:
            return self.get_conversation(owner_id, conversation_id, False)
        updates.append("updated_at=?")
        params.append(time.time())
        params.extend([conversation_id, owner_id])
        with self._lock:
            cur = self._db.execute(
                f"UPDATE conversations SET {','.join(updates)} WHERE id=? AND owner_id=?", params
            )
            self._db.commit()
        return self.get_conversation(owner_id, conversation_id, False) if cur.rowcount else None

    def delete_conversation(self, owner_id: int, conversation_id: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM conversations WHERE id=? AND owner_id=?", (conversation_id, owner_id))
            self._db.commit()
        return bool(cur.rowcount)

    def add_message(self, owner_id: int, conversation_id: str, role: str, content: str, *,
                    bot_id: str | None = None, bot_name: str | None = None,
                    sources: list | None = None, attachments: list | None = None,
                    state: str = "completed") -> dict:
        now = time.time()
        row = {
            "id": str(uuid.uuid4()), "conversation_id": conversation_id, "owner_id": owner_id,
            "role": role, "bot_id": bot_id, "bot_name": bot_name, "content": content,
            "sources_json": _json(sources or []), "attachments_json": _json(attachments or []),
            "state": state, "created_at": now,
        }
        with self._lock:
            self._db.execute(
                """INSERT INTO messages(id,conversation_id,owner_id,role,bot_id,bot_name,content,
                   sources_json,attachments_json,state,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(row.values()),
            )
            self._db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
            self._db.commit()
        return self._message(row)

    def get_message(self, owner_id: int, message_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM messages WHERE id=? AND owner_id=?", (message_id, owner_id)).fetchone()
        return self._message(row) if row else None

    def delete_message(self, owner_id: int, message_id: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM messages WHERE id=? AND owner_id=?", (message_id, owner_id))
            self._db.commit()
        return bool(cur.rowcount)

    def upsert_bot_profile(self, owner_id: int, chatbot_id: str, *, avatar: str = "sparkles",
                           instructions: str = "", enabled: bool = True, color: str = "#6d5dfc") -> dict:
        with self._lock:
            self._db.execute(
                """INSERT INTO bot_profiles(chatbot_id,owner_id,avatar,instructions,enabled,color,updated_at)
                   VALUES (?,?,?,?,?,?,?) ON CONFLICT(chatbot_id) DO UPDATE SET
                   avatar=excluded.avatar,instructions=excluded.instructions,enabled=excluded.enabled,
                   color=excluded.color,updated_at=excluded.updated_at""",
                (chatbot_id, owner_id, avatar, instructions, 1 if enabled else 0, color, time.time()),
            )
            self._db.commit()
        return self.get_bot_profile(owner_id, chatbot_id)

    def get_bot_profile(self, owner_id: int, chatbot_id: str) -> dict:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM bot_profiles WHERE chatbot_id=? AND owner_id=?", (chatbot_id, owner_id)
            ).fetchone()
        if row:
            item = dict(row)
            item["enabled"] = bool(item["enabled"])
            return item
        return {"chatbot_id": chatbot_id, "owner_id": owner_id, "avatar": "sparkles",
                "instructions": "", "enabled": True, "color": "#6d5dfc"}

    def delete_bot_profile(self, owner_id: int, chatbot_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM bot_profiles WHERE chatbot_id=? AND owner_id=?", (chatbot_id, owner_id))
            self._db.commit()


store = WorkspaceStore()
