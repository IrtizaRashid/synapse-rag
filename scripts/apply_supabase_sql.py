"""Apply supabase/schema.sql and supabase/rag_vector.sql to a Supabase Postgres DB."""
import os
import re
import sys

import pg8000.native
import ssl

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def _load_env():
    env = {}
    p = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def split_sql(sql: str):
    """Split a SQL script on top-level semicolons, respecting quotes and dollar-quotes."""
    parts = []
    buf = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and sql[i:i+2] == "--":
            j = sql.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "'":
            buf.append(c)
            i += 1
            while i < n:
                buf.append(sql[i])
                if sql[i] == "'":
                    if i + 1 < n and sql[i+1] == "'":
                        buf.append(sql[i+1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if c == '"':
            buf.append(c)
            i += 1
            while i < n:
                buf.append(sql[i])
                if sql[i] == '"':
                    if i + 1 < n and sql[i+1] == '"':
                        buf.append(sql[i+1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if c == "$":
            m = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[i:])
            if m:
                tag = m.group(0)
                end = sql.find(tag, i + len(tag))
                buf.append(sql[i:end + len(tag)])
                i = end + len(tag)
                continue
        if c == ";":
            stmt = "".join(buf).strip()
            if stmt:
                parts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    stmt = "".join(buf).strip()
    if stmt:
        parts.append(stmt)
    return parts

def main():
    env = _load_env()
    url = env.get("SUPABASE_DB_URL") or os.environ.get("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL not found in .env"); sys.exit(1)
    from urllib.parse import urlparse
    parsed = urlparse(url)
    user = parsed.username
    password = parsed.password
    host = parsed.hostname
    port = parsed.port or 5432
    database = parsed.path.lstrip("/") or "postgres"
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    conn = pg8000.native.Connection(
        user=user, password=password, host=host, port=port,
        database=database, ssl_context=ssl_ctx,
    )
    files = sys.argv[1:] or [os.path.join("supabase", "schema.sql"), os.path.join("supabase", "rag_vector.sql")]
    for f in files:
        print(f"\n== {f} ==")
        sql = open(f, encoding="utf-8").read()
        for idx, stmt in enumerate(split_sql(sql), 1):
            try:
                conn.run(stmt)
                print(f"  ok [{idx}] {stmt.splitlines()[0][:80]}")
            except Exception as exc:
                print(f"  FAIL [{idx}] {stmt.splitlines()[0][:80]}")
                print(f"       {exc}")
                sys.exit(1)
    conn.close()
    print("\nAll SQL applied successfully.")

if __name__ == "__main__":
    main()
