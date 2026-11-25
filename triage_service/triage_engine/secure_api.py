"""Authenticated entry point for the private Streetfix integration."""

import hmac
import os
import re

from fastapi import Request
from fastapi.responses import JSONResponse

from triage_engine.api import app

token = os.environ.get("TRIAGE_ENGINE_SERVICE_TOKEN", "")
if not re.fullmatch(r"[A-Za-z0-9._~-]{32,256}", token):
    raise RuntimeError("Set a strong TRIAGE_ENGINE_SERVICE_TOKEN before starting.")


@app.middleware("http")
async def require_service_token(request: Request, call_next):
    """Reject callers without the shared service credential."""
    supplied = request.headers.get("Authorization", "")
    if not hmac.compare_digest(supplied, f"Bearer {token}"):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)
