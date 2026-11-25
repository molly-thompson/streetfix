"""Verify the authenticated deployment entry point."""

import importlib

from fastapi.testclient import TestClient


def test_secure_entrypoint_requires_token_and_supports_degraded_triage(monkeypatch):
    """Untrusted callers cannot access configuration or submit reports."""
    token = "test-token-" + "x" * 32
    monkeypatch.setenv("TRIAGE_ENGINE_SERVICE_TOKEN", token)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    secure_api = importlib.import_module("triage_engine.secure_api")
    client = TestClient(secure_api.app)

    assert client.get("/api/v1/configs/streetfix").status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    config_response = client.get("/api/v1/configs/streetfix", headers=headers)
    assert config_response.status_code == 200
    response = client.post(
        "/api/v1/triage/configured",
        headers=headers,
        json={
            "configuration": config_response.json(),
            "report": {
                "profile_id": "streetfix",
                "description": "A damaged street light.",
                "allow_degraded_on_ai_error": True,
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
