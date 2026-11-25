"""Tests for organisational YAML/JSON configuration loading and cross-reference validation."""

from __future__ import annotations

import copy
import json

import yaml

from triage_engine.config_loader import ConfigRegistry, validate_raw_config


def test_preset_configs_load_cleanly(config_registry: ConfigRegistry) -> None:
    profiles = {p.profile_id: p for p in config_registry.list_profiles()}
    assert "streetfix" in profiles
    assert "campus_facilities" in profiles
    assert profiles["streetfix"].ai_settings.model_name == "gemini-4-hydrogen"
    assert profiles["campus_facilities"].ai_settings.model_name == "gemini-4-hydrogen"


def _load_streetfix_dict(config_registry: ConfigRegistry) -> dict:
    return config_registry.get("streetfix").model_dump(mode="json")


def test_validate_json_format_supported(config_registry: ConfigRegistry) -> None:
    raw = json.dumps(_load_streetfix_dict(config_registry))
    result = validate_raw_config(raw, "json")
    assert result.valid is True
    assert result.profile_id == "streetfix"


def test_rejects_routing_to_unknown_team(config_registry: ConfigRegistry) -> None:
    cfg = copy.deepcopy(_load_streetfix_dict(config_registry))
    cfg["routing_rules"][0]["team_id"] = "ghost_team"
    result = validate_raw_config(yaml.safe_dump(cfg), "yaml")
    assert result.valid is False
    assert any("unknown team_id 'ghost_team'" in err.message for err in result.errors)


def test_rejects_unrouted_category_without_fallback(config_registry: ConfigRegistry) -> None:
    cfg = copy.deepcopy(_load_streetfix_dict(config_registry))
    cfg["default_fallback_team_id"] = None
    cfg["allow_ai_team_routing_when_unmapped"] = False
    cfg["routing_rules"] = cfg["routing_rules"][1:]
    result = validate_raw_config(yaml.safe_dump(cfg), "yaml")
    assert result.valid is False
    assert any("no routing rule" in err.message for err in result.errors)


def test_rejects_undefined_priority_in_safety_and_priority_rules(config_registry: ConfigRegistry) -> None:
    cfg = copy.deepcopy(_load_streetfix_dict(config_registry))
    cfg["priority_criteria"][0]["priority_id"] = "P99"
    result = validate_raw_config(yaml.safe_dump(cfg), "yaml")
    assert result.valid is False
    assert any("undefined priority_id 'P99'" in err.message for err in result.errors)


def test_rejects_critical_safety_criterion_without_highest_rank(config_registry: ConfigRegistry) -> None:
    cfg = copy.deepcopy(_load_streetfix_dict(config_registry))
    cfg["safety_criteria"][0]["severity"] = "critical"
    cfg["safety_criteria"][0]["minimum_priority_id"] = "P3"
    result = validate_raw_config(yaml.safe_dump(cfg), "yaml")
    assert result.valid is False
    assert any("highest-urgency priority" in err.message for err in result.errors)


def test_rejects_inverted_confidence_thresholds(config_registry: ConfigRegistry) -> None:
    cfg = copy.deepcopy(_load_streetfix_dict(config_registry))
    cfg["confidence_thresholds"] = {
        "abstention_threshold": 0.80,
        "human_review_threshold": 0.50,
        "high_confidence_threshold": 0.90,
    }
    result = validate_raw_config(yaml.safe_dump(cfg), "yaml")
    assert result.valid is False
    assert any("abstention_threshold < human_review_threshold" in err.message for err in result.errors)


def test_rejects_unsupported_provider_and_deprecated_model(config_registry: ConfigRegistry) -> None:
    cfg = copy.deepcopy(_load_streetfix_dict(config_registry))
    cfg["ai_settings"]["provider"] = "unknown_llm"
    cfg["ai_settings"]["model_name"] = "gemini-1.5-flash"
    result = validate_raw_config(yaml.safe_dump(cfg), "yaml")
    assert result.valid is False
    assert len(result.errors) >= 2


def test_rejects_invalid_regex_in_safety_criteria(config_registry: ConfigRegistry) -> None:
    cfg = copy.deepcopy(_load_streetfix_dict(config_registry))
    cfg["safety_criteria"][0]["patterns"] = ["[unclosed(regex"]
    result = validate_raw_config(yaml.safe_dump(cfg), "yaml")
    assert result.valid is False
    assert any("Invalid safety regex pattern" in err.message for err in result.errors)
