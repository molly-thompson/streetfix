"""Security and precedence tests for request-level configuration overrides."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.conftest import ScriptedAIProvider
from triage_engine.config_loader import ConfigRegistry, OverrideValidationError, apply_safe_override
from triage_engine.schemas import RequestConfigOverride, TriageRequest
from triage_engine.service import TriageService


def test_forbidden_override_fields_rejected_by_schema() -> None:
    for forbidden_payload in [
        {"disable_safety": True},
        {"safety_criteria": []},
        {"human_review_rules": {"review_on_safety_escalation": False}},
        {"api_key": "injected-secret"},
        {"routing_rules": []},
    ]:
        with pytest.raises(ValidationError):
            RequestConfigOverride.model_validate(forbidden_payload)


def test_override_cannot_lower_human_review_threshold(config_registry: ConfigRegistry) -> None:
    streetfix_cfg = config_registry.get("streetfix")
    override = RequestConfigOverride(stricter_confidence_floor=0.20)
    with pytest.raises(OverrideValidationError) as exc_info:
        apply_safe_override(streetfix_cfg, override)
    assert any(
        err["error_type"] == "security_precedence_violation"
        for err in exc_info.value.field_errors
    )


def test_override_cannot_select_unpermitted_model(config_registry: ConfigRegistry) -> None:
    streetfix_cfg = config_registry.get("streetfix")
    override = RequestConfigOverride(preferred_model_name="gemini-1.5-pro")
    with pytest.raises(OverrideValidationError) as exc_info:
        apply_safe_override(streetfix_cfg, override)
    assert any(
        err["error_type"] == "unauthorised_model_selection"
        for err in exc_info.value.field_errors
    )


def test_valid_non_weakening_override_tightens_oversight(config_registry: ConfigRegistry) -> None:
    service = TriageService(config_registry, ScriptedAIProvider())
    req = TriageRequest(
        description="Deep pothole on northbound High Street lane near junction.",
        profile_id="streetfix",
        config_override=RequestConfigOverride(
            force_human_review=True,
            stricter_confidence_floor=0.82,
            additional_missing_info_prompts=["Is the pothole blocking a cycle lane?"],
            contextual_notes="Reported during rush hour.",
            preferred_model_name="gemini-4-neon",
        ),
    )
    res = service.triage(req)
    assert res.human_review.required is True
    assert "OVERRIDE_FORCE_REVIEW" in res.deterministic_rules_triggered
    assert res.provider_metadata.model_name == "gemini-4-neon"
    assert any("cycle lane" in m.question for m in res.missing_information)
