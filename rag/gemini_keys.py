from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_index = 0


def gemini_keys() -> list[str]:
    keys = [key.strip() for key in os.getenv("GEMINI_API_KEYS", "").split(",") if key.strip()]
    fallback = os.getenv("GEMINI_API_KEY", "").strip()
    if fallback and fallback not in keys:
        keys.append(fallback)
    return keys


def next_gemini_key() -> str:
    global _index
    keys = gemini_keys()
    if not keys:
        raise RuntimeError("GEMINI_API_KEY or GEMINI_API_KEYS is required.")
    with _lock:
        key = keys[_index % len(keys)]
        _index += 1
    return key
