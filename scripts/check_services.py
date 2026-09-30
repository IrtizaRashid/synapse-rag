"""Read-only service check. Does not print credentials or document content."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
import httpx

headers = {"apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"], "Authorization": "Bearer " + os.environ["SUPABASE_SERVICE_ROLE_KEY"]}
url = os.environ["SUPABASE_URL"].rstrip("/")
with httpx.Client(timeout=20) as client:
    for table in ("rag_chunks", "chatbots"):
        response = client.get(f"{url}/rest/v1/{table}", params={"select":"id", "limit":"1"}, headers=headers)
        print(f"Supabase {table}: HTTP {response.status_code}")
    anon = client.get(f"{url}/rest/v1/rag_chunks", params={"select":"id","limit":"1"}, headers={"apikey":os.environ.get("SUPABASE_ANON_KEY","")})
    print(f"Anonymous vector access: HTTP {anon.status_code}, returned rows: {len(anon.json()) if isinstance(anon.json(),list) else 0}")
