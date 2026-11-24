# Triage policy framework

Status: design draft. No operational policy is approved by this document.

Streetfix is configured for one context per deployment. Different deployments
may serve different organisations and issue domains. Policy configuration must
not assume that the organisation is a council or that reports concern streets.

## Outcomes and evidence

Triage assesses two independent dimensions:

- Priority describes impact or importance. Its fixed codes are `LOW`, `NORMAL`,
  `HIGH`, and `CRITICAL`.
- Urgency describes time sensitivity or immediate safety. Its fixed codes are
  `ROUTINE`, `SOON`, `URGENT`, and `EMERGENCY`.

Labels and explanatory guidance can be configured for a deployment. Codes
remain stable so that work items and integrations have a consistent meaning.
The deployment's approved policy maps predefined, structured evidence to
these outcomes. A sensitive-content modifier, where relevant to an issue type,
may affect priority; it must not affect urgency without separate evidence of
time sensitivity or safety.

The initial evaluator will support bounded, structured conditions over
predefined evidence. It must not execute arbitrary code or infer certainty from
unstructured instructions. A later extension may permit staff-defined evidence
factors and scales; that is not part of the initial schema.

## Configurable policy

The configuration must represent:

- A versioned policy, its approval and activation state.
- An issue-type hierarchy, responsible departments, and issue-specific
  conditions or modifiers.
- Service-area coverage and evidence needed to determine responsibility.
- Structured evidence conditions and their mappings to priority and urgency
  codes, including what happens when conditions conflict or no condition
  applies.
- Human-readable guidance and representative, anonymized policy examples.

The policy's issue taxonomy, service area, evidence conditions, mappings,
modifier definitions, and approved examples are **[CONFIGURABLE /
TENANT-SPECIFIC PENDING]**. Their concrete schema and safe editing interface
must be validated against real requirements before operational use.

The current service-area parser accepts WGS84 GeoJSON Polygon or MultiPolygon
geometries, optionally wrapped in a Feature. It rejects invalid geometries and
boundaries crossing the antimeridian; deployments requiring those boundaries
need explicit support before configuring a service area.

Drafts may configure reporter wording in `evidence_labels` using the keys
`reported_impact`, `reported_time_sensitivity`, and
`reported_sensitive_content`. Each may contain `label`, `guidance`, and a
`choices` object mapping existing evidence codes to labels. Missing labels use
the application defaults; this configuration cannot add new evidence codes.

## Safe evaluation

Evaluate each decision independently and preserve its evidence. A decision is
determined only when the approved policy establishes an unambiguous result;
missing, insufficient, or conflicting evidence must abstain for human review.
Priority and urgency are not interchangeable, and an unknown value must never
be treated as a low-risk default.

Only an approved, active policy may finalize eligible decisions automatically.
Out-of-scope rejection and duplicate linking require human approval regardless
of policy. No automated policy is enabled until the deployment's responsible
staff approve its rubric and representative scenarios.
