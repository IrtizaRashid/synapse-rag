import os
import tempfile
from pathlib import Path

_workspace_temp = tempfile.TemporaryDirectory(prefix="synapse-tests-", ignore_cleanup_errors=True)
os.environ["WORKSPACE_DB_PATH"] = str(Path(_workspace_temp.name) / "workspace.db")
os.environ["UPLOAD_DIR"] = str(Path(_workspace_temp.name) / "uploads")
os.environ["GEMINI_API_KEY"] = ""
os.environ["GEMINI_API_KEYS"] = ""

# Force local backends and disable network/rate limits so the suite is
# deterministic. load_dotenv does not override vars already set here.
os.environ["AUTH_BACKEND"] = "local"
os.environ["AUTH_DB_PATH"] = str(Path(tempfile.gettempdir()) / "rag_test_auth.db")
os.environ["RAG_BACKEND"] = "local"
os.environ["RAG_DATA_PATH"] = str(Path(tempfile.gettempdir()) / "rag_test_chunks.json")
os.environ["CHATBOT_BACKEND"] = "local"
os.environ["CHATBOT_DB_PATH"] = str(Path(tempfile.gettempdir()) / "rag_test_chatbots.json")
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["RESEND_API_KEY"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASS"] = ""
os.environ["ALLOW_DEV_OTP"] = "true"
os.environ["ALLOWED_HOSTS"] = ""
os.environ["ALLOWED_ORIGINS"] = ""
os.environ["COOKIE_SECURE"] = "false"  # test client uses plain http; secure cookies are dropped
os.environ["RAG_API_KEYS"] = "test-api-key"
os.environ["INDEX_INLINE"] = "true"


def pytest_sessionfinish(session, exitstatus):
    for name in ("rag_test_auth.db", "rag_test_chunks.json", "rag_test_chatbots.json"):
        try:
            Path(tempfile.gettempdir(), name).unlink(missing_ok=True)
        except OSError:
            pass
