"""FastAPI REST endpoint and contract tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import CONFIG_DIR, ScriptedAIProvider
from triage_engine.api import create_app
from triage_engine.providers.base import ProviderUnavailableError, TriageAIProvider


class _DownProvider(TriageAIProvider):
    provider_name = "down_provider"

    def analyze_report(self, request, policy):
        raise ProviderUnavailableError("Upstream AI unavailable")


def test_health_configs_scenarios_and_docs_endpoints() -> None:
    app = create_app(config_dir=CONFIG_DIR, ai_provider=ScriptedAIProvider())
    client = TestClient(app)

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert "streetfix" in health.json()["profiles_loaded"]
    assert "campus_facilities" in health.json()["profiles_loaded"]

    configs = client.get("/api/v1/configs")
    assert configs.status_code == 200
    assert len(configs.json()) == 2

    yaml_cfg = client.get("/api/v1/configs/streetfix?format=yaml")
    assert yaml_cfg.status_code == 200
    assert "profile_id: streetfix" in yaml_cfg.text

    scenarios = client.get("/api/v1/scenarios")
    assert scenarios.status_code == 200
    assert len(scenarios.json()) >= 9

    docs = client.get("/docs")
    assert docs.status_code == 200
    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200


def test_triage_and_compare_endpoints() -> None:
    app = create_app(config_dir=CONFIG_DIR, ai_provider=ScriptedAIProvider())
    client = TestClient(app)

    resp = client.post(
        "/api/v1/triage",
        json={
            "description": "Water leaking through the ceiling near an electrical socket.",
            "profile_id": "streetfix",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["safety_assessment"]["escalation_triggered"] is True
    assert data["priority_recommendation"]["priority_id"] == "P1"

    cmp_resp = client.post(
        "/api/v1/triage/compare",
        json={
            "report": {"description": "Water leaking through the ceiling near an electrical socket."},
            "profile_ids": ["streetfix", "campus_facilities"],
        },
    )
    assert cmp_resp.status_code == 200
    cmp_data = cmp_resp.json()
    assert cmp_data["safety_consistency_verified"] is True


def test_api_rejects_unsafe_overrides_and_maps_provider_errors() -> None:
    app = create_app(config_dir=CONFIG_DIR, ai_provider=ScriptedAIProvider())
    client = TestClient(app)

    bad_override = client.post(
        "/api/v1/triage",
        json={
            "description": "Pothole on High Street.",
            "config_override": {"disable_safety": True},
        },
    )
    assert bad_override.status_code == 422

    bad_threshold = client.post(
        "/api/v1/triage",
        json={
            "description": "Pothole on High Street.",
            "config_override": {"stricter_confidence_floor": 0.10},
        },
    )
    assert bad_threshold.status_code == 422

    down_app = create_app(config_dir=CONFIG_DIR, ai_provider=_DownProvider())
    down_client = TestClient(down_app)
    err_resp = down_client.post(
        "/api/v1/triage",
        json={"description": "Pothole on High Street.", "allow_degraded_on_ai_error": False},
    )
    assert err_resp.status_code == 503
    assert err_resp.json()["detail"]["error_code"] == "provider_unavailable"
