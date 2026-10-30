"""
FILE:         scripts/smoke_test.py
WHAT IT DOES: A quick "is the deployed system working AND secure?" check against a RUNNING
              API. Unlike pytest (which builds a fake app in memory), this talks to the real
              server over HTTP, with the real databases and models behind it.
WHERE IT FITS: Phase 12. CI runs it against the Docker stack; run it after any deployment.
              Needs `scripts.bootstrap` to have run first (users + indexed documents).
              Doesn't need the LLM: it checks search, not answers. Without the demo
              personas (a prod stack) the login-based access checks are skipped.
RUN:
    docker compose exec api python -m scripts.smoke_test
    python -m scripts.smoke_test --base-url http://localhost:8000
EXIT CODE:    0 = every check passed, 1 = at least one failed.
"""

import argparse
import os
import secrets
import subprocess
import sys

import httpx
import yaml

from app.core.config import DATA_DIR, get_settings

CREDENTIALS_PATH = DATA_DIR / "org" / "dev_credentials.yaml"
QUESTION = "What is the CEO's base salary?"
SECRET = "310,000"  # appears only in the executive compensation document (clearance 4)

_failures: list[str] = []


# =============================================================================
# 1. HELPERS
# =============================================================================
def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        _failures.append(name)


def login(client: httpx.Client, creds: dict, user_id: str) -> dict[str, str]:
    c = creds[user_id]
    r = client.post("/auth/login", data={"username": c["email"], "password": c["password"]})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def search_texts(client: httpx.Client, headers: dict, body: dict) -> tuple[int, str]:
    r = client.post("/search", json=body, headers=headers)
    texts = " ".join(x["text"] for x in r.json().get("results", [])) if r.is_success else ""
    return r.status_code, texts


def settings_refused(**env: str) -> bool:
    """Does the app refuse to START with these settings? (runs in a separate process)"""
    code = "from app.core.config import Settings; Settings()"
    result = subprocess.run([sys.executable, "-c", code], env={**os.environ, **env},
                            capture_output=True, check=False)
    return result.returncode != 0


# =============================================================================
# 2. THE CHECKS
# =============================================================================
def check_service(client: httpx.Client) -> None:
    print("Service")
    r = client.get("/health/ready")
    check("/health/ready is 200 (database + Qdrant reachable)", r.status_code == 200,
          r.text[:200])
    check("security headers present",
          r.headers.get("cache-control") == "no-store"
          and r.headers.get("x-content-type-options") == "nosniff"
          and "x-request-id" in r.headers)
    r = client.get("/app/")
    check("web UI served with a Content-Security-Policy",
          r.status_code == 200 and "content-security-policy" in r.headers)


def check_authentication(client: httpx.Client, creds: dict) -> None:
    print("Authentication")
    r = client.post("/search", json={"query": QUESTION})
    check("search without a token is refused (401)", r.status_code == 401)
    r = client.post("/search", json={"query": QUESTION},
                    headers={"Authorization": "Bearer not-a-real-token"})
    check("a forged token is refused (401)", r.status_code == 401)
    email = creds["u_intern"]["email"] if creds else "nobody@orbitra.example"
    r = client.post("/auth/login", data={"username": email, "password": "wrong-password"})
    check("a wrong password is refused (401)", r.status_code == 401)


def check_access_control(client: httpx.Client, creds: dict) -> None:
    print("Access control (real search, real models)")
    if not creds:
        print("  SKIP  no demo personas (normal in prod)")
        return
    intern, ceo = login(client, creds, "u_intern"), login(client, creds, "u_ceo")
    status, texts = search_texts(client, intern, {"query": QUESTION})
    check("intern searching for the CEO's salary gets no salary",
          status == 200 and SECRET not in texts, f"status {status}")
    # Identity comes only from the token: extra fields in the body must change nothing.
    spoof = {"query": QUESTION, "clearance": 4, "role": "executive", "user_id": "u_ceo"}
    status, texts = search_texts(client, intern, spoof)
    check("intern claiming CEO clearance in the request still gets nothing",
          SECRET not in texts, f"status {status}")
    status, texts = search_texts(client, ceo, {"query": QUESTION})
    check("CEO finds the salary (so the documents really are indexed)",
          status == 200 and SECRET in texts, f"status {status}")


def check_configuration() -> None:
    print("Configuration safety")
    strong = secrets.token_urlsafe(48)
    check("prod refuses the placeholder JWT secret",
          settings_refused(ENVIRONMENT="prod", JWT_SECRET_KEY="change-me", DEMO_LOGIN="false"))
    check("prod refuses demo login",
          settings_refused(ENVIRONMENT="prod", JWT_SECRET_KEY=strong, DEMO_LOGIN="true"))
    check("prod accepts a strong secret with demo login off",
          not settings_refused(ENVIRONMENT="prod", JWT_SECRET_KEY=strong, DEMO_LOGIN="false"))


# =============================================================================
# 3. ENTRY POINT
# =============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test a running API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    # Demo personas exist only outside prod (seed_users refuses prod).
    creds: dict = {}
    if CREDENTIALS_PATH.is_file() and get_settings().environment != "prod":
        creds = yaml.safe_load(CREDENTIALS_PATH.read_text(encoding="utf-8"))["users"]

    with httpx.Client(base_url=args.base_url, timeout=120) as client:
        check_service(client)
        check_authentication(client, creds)
        check_access_control(client, creds)
    check_configuration()

    print(f"\n{'ALL CHECKS PASSED' if not _failures else f'{len(_failures)} FAILED'}")
    sys.exit(1 if _failures else 0)


if __name__ == "__main__":
    main()

