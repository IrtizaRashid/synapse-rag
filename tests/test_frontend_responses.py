from pathlib import Path

from fastapi.testclient import TestClient

from app import app


STATIC = Path(__file__).resolve().parents[1] / "static"
PAGES = ["login.html", "signup.html", "otp.html", "index.html"]


def test_all_frontend_api_calls_use_safe_json_parser():
    for name in PAGES:
        page = (STATIC / name).read_text(encoding="utf-8")
        if name == "index.html":
            assert "workspace.js" in page
            page += (STATIC / "workspace.js").read_text(encoding="utf-8")
        assert "readApiJson" in page, name
        assert "await r.json()" not in page, name
        assert "return r.json()" not in page, name


def test_api_errors_are_json_not_html():
    client = TestClient(app)
    response = client.post(
        "/api/auth/otp/verify",
        json={"email": "missing@example.com", "purpose": "signup", "code": "123456"},
    )
    assert response.status_code in {400, 404, 429}
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json().get("detail"), str)


def test_unknown_api_route_is_json_not_html():
    response = TestClient(app).get("/api/route-that-does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == "Not Found"
