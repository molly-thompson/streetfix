# AI-Assisted Triage Decision-Support Engine

An independent, configurable **Python REST triage service** (`FastAPI` + `Pydantic v2`) with a minimal React evaluation test bench. It transforms unstructured public-realm and facilities issue reports into transparent, evidence-backed triage recommendations while enforcing non-overridable deterministic safety safeguards and mandatory human-oversight gates.

---

## Architecture Overview

The engine is cleanly decoupled into framework-independent core modules, a replaceable AI provider boundary, externalised organisational YAML/JSON policies, and a stateless FastAPI REST layer:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                Optional Evaluation Gateway (Port 3000)                      │
│   React + Vite Test Bench  ──►  Express Proxy (/api/*, /docs, /openapi)     │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│             Standalone Python FastAPI Service (Uvicorn, Stateless)          │
│                                                                             │
│   REST Endpoints: /api/v1/triage | /api/v1/triage/compare                   │
│                   /api/v1/configs | /api/v1/configs/validate                │
│                   /api/v1/scenarios | /api/v1/health | /docs                │
│                                       │                                     │
│                                       ▼                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │             Framework-Independent Core Engine (triage_engine/)      │   │
│   │                                                                     │   │
│   │  1. ConfigRegistry & Safe Override Guard (YAML/JSON + Cross-Ref)    │   │
│   │  2. SafetyEvaluator (System Safeguards + Negation/Contradiction)    │   │
│   │  3. TriageAIProvider ABC ──► GeminiTriageProvider (google-genai)    │   │
│   │  4. Verifiable Evidence Attribution & Uncertainty Gatekeeper        │   │
│   │  5. Cross-Organisation Comparison & Policy Diff Explainer           │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Decision Support, Never Autonomous Resolution**: Every response separates AI recommendations from confirmed human decisions (`human_review.authority_notice`), never claims an issue was inspected or resolved, and enforces human review on safety escalations, abstentions, unverified evidence, contradictions, and low-certainty outputs.
2. **Configuration Precedence & Override Security**:
   - **System-Level Non-Negotiable Safeguards** (highest priority): Mandatory electrical/water, gas, fire/collapse, traffic life-safety, and sharps/hazmat rules apply identically across every organisation and cannot be disabled.
   - **Authorised Organisational Configuration** (`configs/*.yaml`): Defines categories, priorities, operational teams, routing rules, additive safety criteria, human-review triggers, thresholds, and permitted AI models (`gemini-4-hydrogen` default).
   - **Allowlisted Request Overrides** (`RequestConfigOverride`): Uses `extra="forbid"` and explicit validation to allow only non-weakening contextual adjustments (`force_human_review`, higher confidence floor, extra questions, permitted model choice, contextual notes). Attempts to disable safety, weaken review thresholds, or inject secrets return HTTP `422`.
3. **Verifiable Evidence Attribution**: Separates `reported_facts`, verbatim `evidence_excerpts` (checked substring-by-substring against the submitted report, flagging unverified quotes), `inferred_conclusions` (`explicitly_inferred: true`), and `reasoning_summary`.
4. **Separated Confidence & Uncertainty**: Separates `model_self_assessment` (explicitly labeled as an uncalibrated model estimate, never a validated accuracy percentage), `evidence_quality`, `decision_uncertainty`, and `human_review`.
5. **Explicit Processing States**:
   - `completed`: AI assessment succeeded, deterministic checks ran, evidence verified, output validated.
   - `abstained`: Intentionally withheld recommendations due to insufficient evidence or high uncertainty.
   - `degraded`: Only deterministic safety and completeness checks ran because the AI provider failed (only returned when `allow_degraded_on_ai_error: true`; otherwise upstream failures return structured HTTP `502`/`503`/`504`/`429` errors—never fabricated AI results).

---

## Quick Start

### Prerequisites

- **Python**: Targets Python 3.14.x (`requires-python = ">=3.11"` for compatibility with Python 3.11.2+ runtimes).
- **Environment Variables**: Copy `.env.example` to `.env` and set `GEMINI_API_KEY` for live Gemini evaluation.

### 1. Run the Standalone Python FastAPI Service

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export GEMINI_API_KEY="your-key-here"
.venv/bin/uvicorn triage_engine.api:app --host 0.0.0.0 --port 8001
```

Interactive Swagger documentation is available at `http://localhost:8001/docs`.

### 2. Run with the Web Test Bench (Port 3000)

```bash
npm install
npm run dev
```

The Express gateway starts the Python FastAPI Uvicorn service automatically on `127.0.0.1:8001`, proxies `/api/*`, `/docs`, and `/openapi.json`, and serves the Vite React evaluation console at `http://localhost:3000`.

---

## Organisational Configurations

Two demonstration presets are included under `configs/`:

- `configs/streetfix.yaml` — Municipal public-realm infrastructure (`P1`–`P4` priorities, Highways, Street Cleansing, Street Lighting, Parks, Civic Assets, Triage Duty Desk).
- `configs/campus_facilities.yaml` — University estates & building operations (`C1`–`C4` priorities, Campus MEP Electrical, Building Fabric & Plumbing, HVAC & Lab Systems, Campus Grounds, Custodial, Estates Helpdesk).

Configurations are validated at load time and via `POST /api/v1/configs/validate` for referential integrity:
- Unknown team IDs in `routing_rules` or `default_fallback_team_id`
- Categories without valid routing behaviour
- Undefined priority IDs in `priority_criteria`, `safety_criteria`, or `human_review_rules`
- Critical safety criteria not enforcing the highest urgency rank
- Inverted or contradictory `confidence_thresholds`
- Unsupported AI providers, deprecated models, or invalid regex patterns

### Replacing the AI Provider

Implement `triage_engine.providers.base.TriageAIProvider.analyze_report(request, policy) -> AITriageRawOutput` and pass your provider instance into `TriageService(config_registry, ai_provider)` or `create_app(ai_provider=...)`.

---

## Testing & Limitations

Run the automated offline test suite (uses deterministic scripted provider doubles; requires no live API key):

```bash
.venv/bin/pytest -v
```

Run optional live Gemini integration tests (requires `GEMINI_API_KEY` and `RUN_LIVE_AI_TESTS=1`):

```bash
RUN_LIVE_AI_TESTS=1 .venv/bin/pytest -v -m integration
```

### Documented Limitations

- **Passing tests do not prove real-world accuracy**: Offline tests verify deterministic safety precedence, config validation, override security, verbatim quote checks, abstention gates, and failure handling—not real-world classification accuracy on unseen municipal datasets.
- **Deterministic safety bounds**: Pattern and contextual negation rules catch high-salience explicit hazards (electrical/water contact, gas leaks, fire/collapse, traffic hazards, sharps) and flag uncertain phrasing for review, but cannot guarantee detection of novel, implicit, or domain-unforeseen dangers.
- **Uncalibrated model confidence**: Any numeric estimate in `model_self_assessment` reflects uncalibrated LLM self-reporting and must not be treated as a validated probability.

---

## StreetFix Integration

See [docs/streetfix_django_integration.md](docs/streetfix_django_integration.md) and [docs/examples/api_examples.json](docs/examples/api_examples.json) for the complete Django integration guide and JSON contract examples.
