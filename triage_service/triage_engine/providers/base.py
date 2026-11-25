"""Replaceable AI provider interface and typed failure exceptions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from triage_engine.config_loader import EffectiveTriagePolicy
from triage_engine.schemas import AITriageRawOutput, TriageRequest


class ProviderError(Exception):
    """Base exception for AI provider failures with sanitized public diagnostics."""

    error_code: str = "provider_error"
    http_status: int = 502

    def __init__(self, public_message: str, error_code: str | None = None, http_status: int | None = None) -> None:
        super().__init__(public_message)
        self.public_message = public_message
        if error_code is not None:
            self.error_code = error_code
        if http_status is not None:
            self.http_status = http_status


class ProviderNotConfiguredError(ProviderError):
    error_code = "provider_not_configured"
    http_status = 503


class ProviderTimeoutError(ProviderError):
    error_code = "provider_timeout"
    http_status = 504


class ProviderRateLimitError(ProviderError):
    error_code = "provider_rate_limited"
    http_status = 429


class ProviderUnavailableError(ProviderError):
    error_code = "provider_unavailable"
    http_status = 503


class ProviderMalformedOutputError(ProviderError):
    error_code = "provider_malformed_output"
    http_status = 502


class TriageAIProvider(ABC):
    """Abstract interface decoupling core triage logic from any concrete LLM vendor."""

    provider_name: str = "abstract"

    @abstractmethod
    def analyze_report(
        self,
        request: TriageRequest,
        policy: EffectiveTriagePolicy,
    ) -> AITriageRawOutput:
        """
        Interpret the natural-language report against the active organisational policy.

        Implementations must treat report text as untrusted data, return validated
        AITriageRawOutput, and raise a typed ProviderError subclass on failure.
        """
