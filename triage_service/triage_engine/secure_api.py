"""Authenticated entry point for the private Streetfix integration."""

import hmac
import os
import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from triage_engine.api import app
from triage_engine.config_loader import ConfigRegistry, OverrideValidationError
from triage_engine.config_models import OrganisationalTriageConfig
from triage_engine.providers.base import ProviderError
from triage_engine.providers.gemini_provider import GeminiTriageProvider
from triage_engine.schemas import TriageRequest, TriageResponse
from triage_engine.service import TriageService

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


class ConfiguredTriageRequest(BaseModel):
    """A report and the approved database-backed engine profile."""

    configuration: OrganisationalTriageConfig
    report: TriageRequest


@app.post("/api/v1/triage/configured", response_model=TriageResponse)
def configured_triage(payload: ConfiguredTriageRequest) -> TriageResponse:
    """Validate the profile and evaluate it without changing global service state."""
    config = payload.configuration
    if payload.report.profile_id != config.profile_id:
        raise HTTPException(status_code=422, detail="Profile IDs do not match.")
    service = TriageService(
        ConfigRegistry({config.profile_id: config}), GeminiTriageProvider()
    )
    try:
        return service.triage(payload.report)
    except OverrideValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid configuration override.") from exc
    except ProviderError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.public_message) from exc
