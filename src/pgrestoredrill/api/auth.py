"""Bearer token check. Equal tokens are compared in constant time."""

from __future__ import annotations

import hashlib
import hmac

from fastapi import HTTPException, Request

from pgrestoredrill.api.state import get_state

_MAX_TOKEN = 512


def tokens_match(supplied: str, expected: str) -> bool:
    if not expected or not supplied or len(supplied) > _MAX_TOKEN:
        return False
    supplied_hash = hashlib.sha256(supplied.encode()).digest()
    expected_hash = hashlib.sha256(expected.encode()).digest()
    return hmac.compare_digest(supplied_hash, expected_hash)


def require_admin(request: Request) -> None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    supplied = token.strip() if scheme.lower() == "bearer" else ""
    if tokens_match(supplied, get_state(request.app).settings.admin_token):
        return
    raise HTTPException(
        status_code=401,
        detail="unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )
