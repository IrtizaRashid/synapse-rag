from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

REQUIRED = [
    "GEMINI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "RESEND_API_KEY",
    "MAIL_FROM",
    "RAG_API_KEYS",
    "RAG_API_KEY",
    "N8N_ENCRYPTION_KEY",
    "ALLOWED_HOSTS",
    "ALLOWED_ORIGINS",
]

EXPECTED = {
    "AUTH_BACKEND": "supabase",
    "RAG_BACKEND": "vector",
    "COOKIE_SECURE": "true",
    "TRUST_PROXY": "true",
}


def masked_status(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        return "missing"
    return f"set ({len(value)} chars)"


def main() -> int:
    failed = False
    print("Production config check")
    print("=======================")

    for name in REQUIRED:
        status = masked_status(name)
        print(f"{name}: {status}")
        if status == "missing":
            failed = True

    for name, expected in EXPECTED.items():
        actual = os.getenv(name, "").strip().lower()
        ok = actual == expected
        print(f"{name}: {actual or 'missing'}")
        if not ok:
            failed = True

    api_keys = [key.strip() for key in os.getenv("RAG_API_KEYS", "").split(",") if key.strip()]
    n8n_key = os.getenv("RAG_API_KEY", "").strip()
    if n8n_key and n8n_key not in api_keys:
        print("RAG_API_KEY: not present in RAG_API_KEYS")
        failed = True

    if os.getenv("RAG_API_KEY", "").strip().lower() in {"password", "changeme", "irtiza2150"}:
        print("RAG_API_KEY: too weak")
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
