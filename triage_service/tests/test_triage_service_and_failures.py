"""Tests for AI provider failures and explicit degraded-state handling."""

from __future__ import annotations

import pytest

from triage_engine.config_loader import ConfigRegistry
from triage_engine.providers.base import (
    ProviderError,
    ProviderMalformedOutputError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    TriageAIProvider,
)
from triage_engine.schemas import RoutingSource, TriageRequest, TriageStatus
from triage_engine.service import TriageService


class FailingProvider(TriageAIProvider):
    provider_name = "failing_test_provider"

    def __init__(self, exc: ProviderError) -> None:
        self._exc = exc

    def analyze_report(self, request, policy):
        raise self._exc


@pytest.mark.parametrize(
    "exc",
    [
        ProviderNotConfiguredError("API key missing"),
        ProviderTimeoutError("Timed out"),
        ProviderRateLimitError("Rate limited"),
        ProviderUnavailableError("Service down"),
        ProviderMalformedOutputError("Malformed JSON"),
    ],
)
def test_provider_failure_raises_when_degraded_not_allowed(
    config_registry: ConfigRegistry, exc: ProviderError
) -> None:
    service = TriageService(config_registry, FailingProvider(exc))
    with pytest.raises(type(exc)):
        service.triage(
            TriageRequest(
                description="Exposed wires are sparking near the school crossing.",
                allow_degraded_on_ai_error=False,
            )
        )


def test_degraded_mode_preserves_deterministic_safety_without_fabricating_ai(
    config_registry: ConfigRegistry,
) -> None:
    service = TriageService(
        config_registry,
        FailingProvider(ProviderTimeoutError("Upstream AI timed out")),
    )
    res = service.triage(
        TriageRequest(
            description="Water leaking through the ceiling near an electrical socket.",
            profile_id="streetfix",
            allow_degraded_on_ai_error=True,
        )
    )
    assert res.status == TriageStatus.DEGRADED
    assert res.provider_metadata.ai_assessment_obtained is False
    assert res.provider_metadata.error_code == "provider_timeout"
    assert res.category_recommendation.abstained is True
    assert res.category_recommendation.primary_category_id is None
    assert res.safety_assessment.escalation_triggered is True
    assert res.priority_recommendation.priority_id == "P1"
    assert res.priority_recommendation.escalated_by_safety is True
    assert res.routing_recommendation.routing_source == RoutingSource.UNASSIGNED_FOR_REVIEW
    assert res.human_review.required is True
    assert len(res.evidence_and_reasoning.inferred_conclusions) == 0


def test_gemini_provider_retries_transient_503_and_recovers(
    config_registry: ConfigRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from google.genai import errors as genai_errors
    from triage_engine.config_loader import apply_safe_override
    from triage_engine.providers.gemini_provider import GeminiTriageProvider
    from triage_engine.schemas import (
        AITriageRawOutput,
        DecisionUncertaintyLevel,
        EvidenceQualityLevel,
        QualitativeConfidence,
    )

    sample_json = AITriageRawOutput(
        suggested_category_id="potholes_roads",
        suggested_priority_id="P3",
        priority_rationale="Standard defect.",
        routing_rationale="Highways.",
        reported_facts=["Deep pothole on High Street."],
        evidence_excerpts=[],
        inferred_conclusions=[],
        reasoning_summary="Recovered after transient 503.",
        model_qualitative_confidence=QualitativeConfidence.HIGH,
        model_uncalibrated_estimate=0.90,
        evidence_quality=EvidenceQualityLevel.SUFFICIENT,
        evidence_quality_explanation="Clear.",
        decision_uncertainty=DecisionUncertaintyLevel.LOW,
        decision_uncertainty_explanation="Clear.",
        recommend_human_review=False,
    ).model_dump_json()

    attempts = {"count": 0}

    class FakeModels:
        def generate_content(self, **_kwargs):
            attempts["count"] += 1
            if attempts["count"] <= 2:
                raise genai_errors.APIError(
                    503,
                    {"error": {"code": 503, "message": "Service unavailable", "status": "UNAVAILABLE"}},
                )
            return SimpleNamespace(text=sample_json)

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.models = FakeModels()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key-value")
    monkeypatch.setattr("triage_engine.providers.gemini_provider.genai.Client", FakeClient)
    monkeypatch.setattr("triage_engine.providers.gemini_provider.time.sleep", lambda _s: None)

    provider = GeminiTriageProvider(max_retries=3)
    policy = apply_safe_override(config_registry.get("streetfix"), None)
    out = provider.analyze_report(TriageRequest(description="Deep pothole on High Street."), policy)
    assert attempts["count"] == 3
    assert out.suggested_category_id == "potholes_roads"


def test_gemini_provider_raises_unavailable_when_503_retries_exhausted(
    config_registry: ConfigRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from google.genai import errors as genai_errors
    from triage_engine.config_loader import apply_safe_override
    from triage_engine.providers.gemini_provider import GeminiTriageProvider

    class Always503Models:
        def generate_content(self, **_kwargs):
            raise genai_errors.APIError(
                503,
                {"error": {"code": 503, "message": "Service unavailable", "status": "UNAVAILABLE"}},
            )

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.models = Always503Models()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key-value")
    monkeypatch.setattr("triage_engine.providers.gemini_provider.genai.Client", FakeClient)
    monkeypatch.setattr("triage_engine.providers.gemini_provider.time.sleep", lambda _s: None)

    provider = GeminiTriageProvider(max_retries=2)
    policy = apply_safe_override(config_registry.get("streetfix"), None)
    with pytest.raises(ProviderUnavailableError):
        provider.analyze_report(TriageRequest(description="Deep pothole on High Street."), policy)

