"""
FILE:         app/core/rate_limit.py
WHAT IT DOES: Limits how many requests one user (or one IP address) can make per minute.
              Too many -> HTTP 429 "Too Many Requests" with a Retry-After header.
WHERE IT FITS: Phase 8. Protects against:
                - password guessing on /auth/login           (limited per IP)
                - attackers hammering /query with injection
                  attempts, and one user hogging the GPU      (limited per user)
USED BY:      api/auth.py, api/search.py, api/query.py, api/admin.py.

How it works ("sliding window"): remember the time of each recent request per key; drop
the ones older than 60 s; if what's left has reached the limit, refuse.

Limitation: counts live in this process's memory. With several API servers you would keep
them in a shared store (e.g. Redis) instead - a single server is fine for this project.
"""

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

from app.audit import service as audit
from app.auth.dependencies import CurrentUser
from app.core.config import get_settings

WINDOW_SECONDS = 60.0


# =============================================================================
# 1. THE LIMITER
# =============================================================================
class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()  # FastAPI serves requests on several threads

    def hit(self, key: str, limit: int, window: float = WINDOW_SECONDS) -> float | None:
        """Record one request. Returns None if allowed, else seconds until a retry works."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window:  # forget requests outside the window
                hits.popleft()
            if len(hits) >= limit:
                return hits[0] + window - now
            hits.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def _too_many(retry_after: float) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many requests. Please slow down.",
        headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
    )


# =============================================================================
# 2. FASTAPI DEPENDENCIES - add to a route with `dependencies=[Depends(...)]`
# =============================================================================
# Per logged-in user. The user comes from the verified token (CurrentUser), so one person
# cannot dodge the limit by changing IP, and colleagues behind one office IP don't share it.
def limit_per_user(scope: str) -> Callable[[Request, CurrentUser], None]:
    def dependency(request: Request, user: CurrentUser) -> None:
        limit = getattr(get_settings(), f"rate_limit_{scope}")
        retry = limiter.hit(f"{scope}:user:{user.user_id}", limit)
        if retry is not None:
            audit.record(scope, outcome="rate_limited", user=user, request=request)
            raise _too_many(retry)

    return dependency


# Per client IP - for login, where there is no verified user yet.
def limit_per_ip(scope: str) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        limit = getattr(get_settings(), f"rate_limit_{scope}")
        ip = request.client.host if request.client else "unknown"
        retry = limiter.hit(f"{scope}:ip:{ip}", limit)
        if retry is not None:
            audit.record(scope, outcome="rate_limited", request=request)
            raise _too_many(retry)

    return dependency
