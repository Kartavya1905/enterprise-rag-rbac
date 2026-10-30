"""
FILE:         tests/unit/test_passwords.py
WHAT IT TESTS: bcrypt hashing and verification (app/auth/passwords.py).
WHERE IT FITS: Phase 3.
"""

import pytest

from app.auth.passwords import hash_password, verify_password


# TEST 1: right password verifies; wrong one doesn't.
def test_hash_then_verify(test_env: None) -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


# TEST 2: the stored hash never contains the password itself.
def test_hash_does_not_contain_password(test_env: None) -> None:
    assert "s3cret-value" not in hash_password("s3cret-value")


# TEST 3: same password twice -> different hashes (random salt each time).
def test_same_password_gets_different_salts(test_env: None) -> None:
    assert hash_password("same") != hash_password("same")


# TEST 4: bcrypt ignores bytes after 72 - we reject instead of silently truncating.
def test_over_long_passwords_are_rejected(test_env: None) -> None:
    with pytest.raises(ValueError):
        hash_password("a" * 73)
    assert not verify_password("a" * 73, hash_password("a" * 72))
