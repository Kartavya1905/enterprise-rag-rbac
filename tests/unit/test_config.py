"""
FILE:         tests/unit/test_config.py
WHAT IT TESTS: Settings loading and the production safety check (app/core/config.py).
WHERE IT FITS: Phase 1.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make_settings(**overrides) -> Settings:
    # Ignore any developer .env so tests are deterministic.
    return Settings(_env_file=None, **overrides)


# TEST 1: production + the placeholder secret "change-me" -> refuse to start.
def test_prod_rejects_default_jwt_secret(test_env: None) -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        make_settings(environment="prod", jwt_secret_key="change-me")


# TEST 2: production + a long random secret -> fine.
def test_prod_accepts_custom_jwt_secret(test_env: None) -> None:
    secret = "k" * 40
    settings = make_settings(environment="prod", jwt_secret_key=secret)
    assert settings.jwt_secret_key.get_secret_value() == secret


# TEST 2b: production + a short (guessable) secret -> refuse to start.
def test_prod_rejects_short_jwt_secret(test_env: None) -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        make_settings(environment="prod", jwt_secret_key="short-secret")


# TEST 3: no QDRANT_URL -> embedded mode; with a URL -> server mode.
def test_embedded_qdrant_when_no_url(test_env: None) -> None:
    assert make_settings().qdrant_is_remote is False
    assert make_settings(qdrant_url="http://localhost:6333").qdrant_is_remote is True


# TEST 4: printing the settings must not reveal the secret (SecretStr shows "**********").
def test_secrets_are_not_printed(test_env: None) -> None:
    settings = make_settings(jwt_secret_key="super-secret")
    assert "super-secret" not in repr(settings)
