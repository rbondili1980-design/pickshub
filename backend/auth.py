"""
JWT + bcrypt authentication for PicksHub.

Flow:
  POST /api/login  →  verify bcrypt hash  →  return signed JWT
  All endpoints    →  validate JWT Bearer token  →  extract role

Roles:
  admin  — full access (read + write, scrape, grade)
  guest  — read-only (Dashboard + Tracker only)

Passwords stored as bcrypt hashes in .env (ADMIN_PASS_HASH / GUEST_PASS_HASH).
Plaintext passwords never leave the Mac.

Rate limiting:
  Max 5 failed login attempts per IP per 15-minute window → 429.
"""
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# ── Config ────────────────────────────────────────────────────────────────────
_JWT_SECRET      = os.getenv("JWT_SECRET", "change-me-in-production")
_JWT_ALGORITHM   = "HS256"
_JWT_EXPIRE_HRS  = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

bearer = HTTPBearer(auto_error=False)

# ── Rate limiter ──────────────────────────────────────────────────────────────
_WINDOW_SECS  = 15 * 60
_MAX_FAILURES = 5
_failures: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str):
    now = time.monotonic()
    _failures[ip] = [t for t in _failures[ip] if now - t < _WINDOW_SECS]
    if len(_failures[ip]) >= _MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {_WINDOW_SECS // 60} minutes.",
        )


def _record_failure(ip: str):
    _failures[ip].append(time.monotonic())


def _clear_failures(ip: str):
    _failures.pop(ip, None)


# ── User registry (bcrypt hashes) ─────────────────────────────────────────────
def _users() -> dict[str, tuple[str, str]]:
    """Return {username: (bcrypt_hash, role)}."""
    return {
        os.getenv("ADMIN_USER", "admin"): (
            os.getenv("ADMIN_PASS_HASH", ""),
            "admin",
        ),
        os.getenv("GUEST_USER", "guest"): (
            os.getenv("GUEST_PASS_HASH", ""),
            "guest",
        ),
    }


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────
def create_token(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=_JWT_EXPIRE_HRS)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> tuple[str, str]:
    """Decode and verify JWT. Returns (username, role). Raises 401 on failure."""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        username = payload.get("sub")
        role     = payload.get("role")
        if not username or not role:
            raise ValueError("missing claims")
        return username, role
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token invalid or expired — please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Login helper (used by /api/login endpoint) ────────────────────────────────
def authenticate(username: str, password: str, ip: str) -> tuple[str, str]:
    """
    Validate credentials against bcrypt hashes.
    Returns (username, role) on success.
    Raises 401/429 on failure.
    """
    _check_rate_limit(ip)
    users = _users()
    if username in users:
        hashed, role = users[username]
        if hashed and verify_password(password, hashed):
            _clear_failures(ip)
            return username, role
    _record_failure(ip)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password",
    )


# ── FastAPI dependencies ──────────────────────────────────────────────────────
def _get_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required — please log in",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


def require_auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    """Any authenticated user (admin or guest). Returns username."""
    token = _get_token(credentials)
    username, _ = decode_token(token)
    return username


def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    """Admin only. Returns username. Raises 403 for guest."""
    token = _get_token(credentials)
    username, role = decode_token(token)
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return username


def get_role(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    """Returns 'admin' or 'guest' for the authenticated user."""
    token = _get_token(credentials)
    _, role = decode_token(token)
    return role
