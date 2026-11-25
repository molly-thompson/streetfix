"""FastAPI REST layer exposing the standalone triage decision-support engine."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import yaml
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from triage_engine.config_loader import (
    ConfigRegistry,
    OverrideValidationError,
    validate_raw_config,
)
from triage_engine.providers.base import ProviderError, TriageAIProvider
from triage_engine.providers.gemini_provider import GeminiTriageProvider
from triage_engine.scenarios import EVALUATION_SCENARIOS, EvaluationScenario
from triage_engine.schemas import (
    TriageCompareRequest,
    TriageCompareResponse,
    TriageRequest,
    TriageResponse,
)
from triage_engine.service import TriageService

MAX_HTTP_BODY_BYTES = 150 * 1024  # 150 KB upper limit across API endpoints

logging.basicConfig(
    level=os.environ.get("TRIAGE_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("triage_engine.api")


class ConfigSummary(BaseModel):
    profile_id: str
    organisation_name: str
    domain_description: str
    model_name: str
    permitted_models: list[str]
    category_count: int
    priority_count: int
    team_count: int
    safety_criterion_count: int


class RawConfigValidateRequest(BaseModel):
    format: Literal["yaml", "json"] = "yaml"
    content: str = Field(..., min_length=1, max_length=120_000)


def create_app(
    config_dir: Path | None = None,
    ai_provider: TriageAIProvider | None = None,
) -> FastAPI:
    """Application factory enabling clean dependency injection for tests and deployments."""
    resolved_dir = config_dir or Path(os.environ.get("TRIAGE_CONFIG_DIR", "./configs"))
    registry = ConfigRegistry.from_directory(resolved_dir)
    provider = ai_provider or GeminiTriageProvider()
    triage_service = TriageService(config_registry=registry, ai_provider=provider)

    app = FastAPI(
        title="AI-Assisted Triage Decision-Support Engine",
        description=(
            "Standalone, configurable REST decision-support service for local-infrastructure and "
            "facilities issue triage. Provides deterministic safety escalation, verifiable evidence "
            "attribution, separated uncertainty metrics, and cross-organisation comparison."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.middleware("http")
    async def enforce_body_size_limit(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_HTTP_BODY_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                content={
                    "error": "payload_too_large",
                    "detail": f"Request payload exceeds maximum limit of {MAX_HTTP_BODY_BYTES // 1024} KB.",
                },
            )
        return await call_next(request)

    @app.get("/api/v1/health", tags=["System"])
    def health() -> dict[str, object]:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        return {
            "status": "ok",
            "profiles_loaded": [p.profile_id for p in registry.list_profiles()],
            "ai_provider": provider.provider_name,
            "ai_credentials_configured": bool(api_key and api_key != "MY_GEMINI_API_KEY"),
        }

    @app.get("/api/v1/configs", response_model=list[ConfigSummary], tags=["Configuration"])
    def list_configs() -> list[ConfigSummary]:
        return [
            ConfigSummary(
                profile_id=cfg.profile_id,
                organisation_name=cfg.organisation_name,
                domain_description=cfg.domain_description,
                model_name=cfg.ai_settings.model_name,
                permitted_models=cfg.ai_settings.permitted_models,
                category_count=len(cfg.categories),
                priority_count=len(cfg.priorities),
                team_count=len(cfg.teams),
                safety_criterion_count=len(cfg.safety_criteria),
            )
            for cfg in registry.list_profiles()
        ]

    @app.get("/api/v1/configs/{profile_id}", tags=["Configuration"])
    def get_config(
        profile_id: str,
        fmt: Literal["json", "yaml"] = Query(default="json", alias="format"),
    ):
        try:
            cfg = registry.get(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        if fmt == "yaml":
            yaml_text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False)
            return PlainTextResponse(content=yaml_text, media_type="text/yaml")
        return cfg.model_dump(mode="json")

    @app.post("/api/v1/configs/validate", tags=["Configuration"])
    def validate_config_endpoint(payload: RawConfigValidateRequest):
        result = validate_raw_config(payload.content, payload.format)
        return result.model_dump(mode="json")

    @app.get("/api/v1/scenarios", response_model=list[EvaluationScenario], tags=["Evaluation"])
    def list_scenarios() -> list[EvaluationScenario]:
        return EVALUATION_SCENARIOS

    @app.post("/api/v1/triage", response_model=TriageResponse, tags=["Triage"])
    def evaluate_triage(payload: TriageRequest) -> TriageResponse:
        try:
            return triage_service.triage(payload)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except OverrideValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"message": exc.message, "field_errors": exc.field_errors},
            ) from exc
        except ProviderError as exc:
            raise HTTPException(
                status_code=exc.http_status,
                detail={"error_code": exc.error_code, "message": exc.public_message},
            ) from exc

    @app.post("/api/v1/triage/compare", response_model=TriageCompareResponse, tags=["Triage"])
    def compare_triage(payload: TriageCompareRequest) -> TriageCompareResponse:
        try:
            return triage_service.compare(payload)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(
                status_code=exc.http_status,
                detail={"error_code": exc.error_code, "message": exc.public_message},
            ) from exc

    return app


app = create_app()
