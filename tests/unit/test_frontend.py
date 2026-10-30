"""
FILE:         tests/unit/test_frontend.py
WHAT IT TESTS: The web UI is served safely (app/main.py + app/web/*) and the dev-only
              demo login (app/api/auth.py) is really off unless switched on.
WHERE IT FITS: Phase 10.

Sections:
    SERVING         /, /app/, static files, Content-Security-Policy
    XSS POLICY      the JavaScript never writes HTML from strings
    DEMO LOGIN      off by default (404), works when on, refused in prod, audited
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.main import CONTENT_SECURITY_POLICY, WEB_DIR

# =============================================================================
# SERVING
# =============================================================================


def test_root_redirects_to_the_ui(client: TestClient) -> None:
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 307 and resp.headers["location"] == "/app/"


def test_ui_is_served_with_a_strict_csp(client: TestClient) -> None:
    resp = client.get("/app/")
    assert resp.status_code == 200 and "Orbitra Assist" in resp.text
    assert resp.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert "script-src 'self'" in CONTENT_SECURITY_POLICY
    assert "'unsafe-inline'" not in CONTENT_SECURITY_POLICY
    js = client.get("/app/js/main.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]


def test_page_has_no_inline_scripts_or_styles() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)  # comments may mention tags
    assert all("src=" in tag for tag in re.findall(r"<script[^>]*>", html))
    assert "<style" not in html and "style=" not in html
    assert "onclick=" not in html.lower()


def test_developer_docs_keep_working(client: TestClient) -> None:
    resp = client.get("/docs")  # Swagger loads from a CDN, so no CSP there
    assert resp.status_code == 200
    assert "content-security-policy" not in resp.headers


# =============================================================================
# XSS POLICY - no HTML is ever built from strings
# =============================================================================
_DANGEROUS = ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
              "new Function"]


@pytest.mark.parametrize("path", sorted(WEB_DIR.glob("js/*.js")), ids=lambda p: Path(p).name)
def test_javascript_never_writes_html(path: Path) -> None:
    code = path.read_text(encoding="utf-8")
    # Ignore comments (they explain the rule and mention innerHTML on purpose).
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", code, flags=re.DOTALL)
    for sink in _DANGEROUS:
        assert sink not in code, f"{path.name} uses {sink}"


# =============================================================================
# DEMO LOGIN
# =============================================================================
def test_demo_login_is_off_by_default(client: TestClient, seeded) -> None:
    assert client.get("/auth/demo-users").status_code == 404
    assert client.post("/auth/demo-login", json={"user_id": "u_ceo"}).status_code == 404


@pytest.fixture
def demo_on(client: TestClient, seeded, monkeypatch):
    monkeypatch.setenv("DEMO_LOGIN", "true")
    get_settings.cache_clear()
    return client


def test_demo_users_lists_people_without_secrets(demo_on) -> None:
    users = demo_on.get("/auth/demo-users").json()
    assert {u["user_id"] for u in users} >= {"u_intern", "u_ceo", "u_it_admin"}
    assert all("password" not in str(u).lower() for u in users)
    assert users[0]["clearance"] <= users[-1]["clearance"]  # sorted by clearance


def test_demo_login_issues_a_normal_token(demo_on) -> None:
    token = demo_on.post("/auth/demo-login", json={"user_id": "u_cfo"}).json()["access_token"]
    me = demo_on.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["user_id"] == "u_cfo" and me["clearance"] == 4
    assert demo_on.post("/auth/demo-login", json={"user_id": "u_ghost"}).status_code == 404


def test_demo_login_is_audited(demo_on) -> None:
    from sqlalchemy import select

    from app.audit.models import AuditEvent
    from app.core.database import get_session_factory

    demo_on.post("/auth/demo-login", json={"user_id": "u_intern"})
    with get_session_factory()() as db:
        event = db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc())).first()
    assert event.event_type == "login" and event.detail == {"method": "demo_login"}


def test_prod_refuses_to_start_with_demo_login(test_env) -> None:
    with pytest.raises(ValidationError, match="DEMO_LOGIN"):
        Settings(_env_file=None, environment="prod", jwt_secret_key="k" * 40, demo_login=True)
