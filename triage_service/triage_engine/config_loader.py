"""External configuration loading, validation, registry, and safe override enforcement."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ValidationError

from triage_engine.config_models import OrganisationalTriageConfig
from triage_engine.schemas import RequestConfigOverride

MAX_CONFIG_BYTES = 100 * 1024  # 100 KB limit for uploaded/file configurations


class ConfigLoadError(Exception):
    """Raised when an organisational configuration file cannot be parsed or validated."""

    def __init__(self, message: str, field_errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field_errors = field_errors or []


class OverrideValidationError(Exception):
    """Raised when a request-level override violates security or precedence boundaries."""

    def __init__(self, message: str, field_errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field_errors = field_errors or []


class ValidationIssue(BaseModel):
    field: str
    message: str
    error_type: str


class ConfigValidationResult(BaseModel):
    valid: bool
    profile_id: str | None = None
    organisation_name: str | None = None
    errors: list[ValidationIssue] = []
    warnings: list[str] = []


@dataclass(frozen=True)
class EffectiveTriagePolicy:
    """Resolved, immutable policy combining org config with verified non-weakening overrides."""

    org_config: OrganisationalTriageConfig
    effective_model_name: str
    effective_human_review_threshold: float
    force_human_review: bool
    additional_missing_info_prompts: tuple[str, ...]
    contextual_notes: str | None
    override_applied: bool


def _format_pydantic_errors(exc: ValidationError) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", [])) or "__root__"
        issues.append(
            ValidationIssue(
                field=loc,
                message=str(err.get("msg", "Invalid configuration value.")),
                error_type=str(err.get("type", "validation_error")),
            )
        )
    return issues


def parse_raw_config_text(content: str, fmt: Literal["yaml", "json"]) -> dict[str, Any]:
    """Safely parse YAML or JSON config text with size bounds."""
    if len(content.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ConfigLoadError(
            f"Configuration exceeds maximum allowed size of {MAX_CONFIG_BYTES // 1024} KB.",
            field_errors=[{"field": "__root__", "message": "Payload too large", "error_type": "size_limit"}],
        )
    try:
        if fmt == "json":
            parsed = json.loads(content)
        else:
            parsed = yaml.safe_load(content)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ConfigLoadError(
            f"Failed to parse {fmt.upper()} configuration: {exc}",
            field_errors=[{"field": "__root__", "message": str(exc), "error_type": f"{fmt}_parse_error"}],
        ) from exc

    if not isinstance(parsed, dict):
        raise ConfigLoadError(
            "Configuration root must be a mapping/object.",
            field_errors=[{"field": "__root__", "message": "Expected mapping/object at root", "error_type": "type_error"}],
        )
    return parsed


def validate_raw_config(content: str, fmt: Literal["yaml", "json"]) -> ConfigValidationResult:
    """Validate raw YAML or JSON configuration text and return structured field errors."""
    try:
        raw_dict = parse_raw_config_text(content, fmt)
    except ConfigLoadError as exc:
        return ConfigValidationResult(
            valid=False,
            errors=[ValidationIssue(**err) for err in exc.field_errors],
        )

    try:
        cfg = OrganisationalTriageConfig.model_validate(raw_dict)
    except ValidationError as exc:
        return ConfigValidationResult(
            valid=False,
            errors=_format_pydantic_errors(exc),
        )

    warnings: list[str] = []
    if not cfg.safety_criteria:
        warnings.append(
            "No organisation-specific safety_criteria configured; mandatory system-level safeguards still apply."
        )
    return ConfigValidationResult(
        valid=True,
        profile_id=cfg.profile_id,
        organisation_name=cfg.organisation_name,
        warnings=warnings,
    )


def load_config_from_file(file_path: Path) -> OrganisationalTriageConfig:
    """Load and validate an organisational configuration file (.yaml, .yml, or .json)."""
    if not file_path.exists():
        raise ConfigLoadError(f"Configuration file not found: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        fmt: Literal["yaml", "json"] = "yaml"
    elif suffix == ".json":
        fmt = "json"
    else:
        raise ConfigLoadError(f"Unsupported configuration extension '{suffix}'. Use .yaml, .yml, or .json.")

    content = file_path.read_text(encoding="utf-8")
    raw_dict = parse_raw_config_text(content, fmt)
    try:
        return OrganisationalTriageConfig.model_validate(raw_dict)
    except ValidationError as exc:
        issues = [issue.model_dump() for issue in _format_pydantic_errors(exc)]
        raise ConfigLoadError(
            f"Configuration validation failed for '{file_path.name}'.",
            field_errors=issues,
        ) from exc


def apply_safe_override(
    org_config: OrganisationalTriageConfig,
    override: RequestConfigOverride | None,
) -> EffectiveTriagePolicy:
    """
    Apply an allowlisted request-level override on top of an authorised org config.

    Precedence:
      1. System-level non-negotiable safeguards (enforced independently in safety/service)
      2. Authorised organisational configuration
      3. Allowlisted, non-weakening request overrides
    """
    base_threshold = org_config.confidence_thresholds.human_review_threshold
    base_model = org_config.ai_settings.model_name

    if override is None:
        return EffectiveTriagePolicy(
            org_config=org_config,
            effective_model_name=base_model,
            effective_human_review_threshold=base_threshold,
            force_human_review=False,
            additional_missing_info_prompts=(),
            contextual_notes=None,
            override_applied=False,
        )

    errors: list[dict[str, Any]] = []
    effective_threshold = base_threshold
    if override.stricter_confidence_floor is not None:
        if override.stricter_confidence_floor < base_threshold:
            errors.append(
                {
                    "field": "config_override.stricter_confidence_floor",
                    "message": (
                        f"Request override cannot lower human_review_threshold below organisational "
                        f"minimum ({base_threshold:.2f})."
                    ),
                    "error_type": "security_precedence_violation",
                }
            )
        elif override.stricter_confidence_floor >= org_config.confidence_thresholds.high_confidence_threshold:
            # Permissible to be strict, even forcing review across most outputs
            effective_threshold = override.stricter_confidence_floor
        else:
            effective_threshold = override.stricter_confidence_floor

    effective_model = base_model
    if override.preferred_model_name is not None:
        if override.preferred_model_name not in org_config.ai_settings.permitted_models:
            errors.append(
                {
                    "field": "config_override.preferred_model_name",
                    "message": (
                        f"Model '{override.preferred_model_name}' is not permitted by organisation "
                        f"'{org_config.profile_id}'. Permitted: {org_config.ai_settings.permitted_models}."
                    ),
                    "error_type": "unauthorised_model_selection",
                }
            )
        else:
            effective_model = override.preferred_model_name

    if errors:
        raise OverrideValidationError(
            "Request configuration override violates organisational policy boundaries.",
            field_errors=errors,
        )

    return EffectiveTriagePolicy(
        org_config=org_config,
        effective_model_name=effective_model,
        effective_human_review_threshold=effective_threshold,
        force_human_review=override.force_human_review,
        additional_missing_info_prompts=tuple(p.strip() for p in override.additional_missing_info_prompts if p.strip()),
        contextual_notes=override.contextual_notes.strip() if override.contextual_notes else None,
        override_applied=True,
    )


class ConfigRegistry:
    """In-memory registry of validated organisational triage profiles loaded from disk."""

    def __init__(self, configs: dict[str, OrganisationalTriageConfig] | None = None) -> None:
        self._configs: dict[str, OrganisationalTriageConfig] = dict(configs or {})

    @classmethod
    def from_directory(cls, directory: Path) -> ConfigRegistry:
        if not directory.exists() or not directory.is_dir():
            raise ConfigLoadError(f"Configuration directory does not exist: {directory}")

        loaded: dict[str, OrganisationalTriageConfig] = {}
        files = sorted(
            [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in (".yaml", ".yml", ".json")]
        )
        if not files:
            raise ConfigLoadError(f"No YAML or JSON configuration files found in {directory}")

        for path in files:
            cfg = load_config_from_file(path)
            if cfg.profile_id in loaded:
                raise ConfigLoadError(
                    f"Duplicate profile_id '{cfg.profile_id}' found in configuration directory '{directory}'."
                )
            loaded[cfg.profile_id] = cfg

        return cls(loaded)

    def list_profiles(self) -> list[OrganisationalTriageConfig]:
        return [self._configs[k] for k in sorted(self._configs.keys())]

    def get(self, profile_id: str) -> OrganisationalTriageConfig:
        if profile_id not in self._configs:
            available = ", ".join(sorted(self._configs.keys()))
            raise KeyError(f"Unknown organisational profile '{profile_id}'. Available profiles: [{available}].")
        return self._configs[profile_id]

    def has(self, profile_id: str) -> bool:
        return profile_id in self._configs
