# Triage policy lifecycle and review

Status: design draft. The deployment's policy and approval roles are
**[CONFIGURABLE / TENANT-SPECIFIC PENDING]**.

## Policy changes

Authorized staff may prepare a draft policy version, including its structured
conditions, mappings, guidance, and examples. A separately authorized
approver must explicitly approve and activate a version before it drives
automatic decisions. Activation must validate references, permitted conditions,
outcome codes, and conflicts. The active version must be immutable: amendments
create a new draft rather than changing the meaning of recorded decisions.

Each triage attempt records the policy version actually used, its input
evidence, per-field outcomes and rationale, and any human corrections. Policy
changes do not silently rewrite past decisions. Which staff can draft,
approve, and activate policies is a deployment decision.

Activation captures the current issue hierarchy, sensitive-content eligibility,
and department names and mappings. If that taxonomy changes, or an older active
policy has no snapshot, new reports go to human review without rule proposals;
prepare and approve a new version to resume proposals. Urgent-review text cues
still apply. This drift check does not by itself make taxonomy changes or
automatic decisions safe under all concurrent writes.

## Intake and human review

An intake submission is preserved independently of an operational work item.
The selected issue path, description, and optional map pin are evidence. The
service-area boundary can help establish coverage, but neither a pin nor a
description alone establishes asset or property ownership.

Deterministic evaluation runs after the submission is saved. Incomplete,
conflicting, or unrecognized evidence, including uncertain ownership or an
unresolved location, is sent to a central staff review queue. Emergency cues
receive an urgent queue flag; this workflow does not provide an emergency
response or promise immediate action.

An approved policy may provide literal urgent-review phrases. Matches in the
report description flag the queue for human attention; they do not assign an
urgency. Literal matching can miss unlisted wording or flag negated phrases,
so it must not be relied on as an emergency-response mechanism.

An authorized reviewer may correct a location and record why. Staff confirm
out-of-scope rejections and duplicate links; possible duplicates are suggestions
only. One authorized reviewer may make these ordinary triage decisions; record
the reviewer, outcome, and reason, including for reports that never reach a
department. AI-supported proposals always need human review.

Departmental routing and assignment provide subsequent operational oversight,
but do not by themselves guarantee a formal second approval. Where a deployment
requires a four-eyes check for critical, emergency, or AI-supported work, it
belongs in the department's workflow and should apply only to the cases defined
by its approved policy. Do not delay urgent work with an additional triage
approval by default.

A new work item is created only when the report is in scope, not linked to an
existing item, and its issue type, department, priority, urgency, and reliable
location are resolved. It begins as `TRIAGED`. Closed and cancelled work
cannot receive a duplicate link. A match to resolved work is a possible
recurrence; a reviewer may link it only after confirming it is the same
issue, rather than a recurrence.

An approved policy may set both `duplicate_distance_m` and
`duplicate_age_days` to suggest work created within that distance and age.
Without both settings, the review interface falls back to exact-pin matching.
The proximity search checks at most 500 recent records in the bounding area
and displays at most 20; it is not an exhaustive duplicate check. Manual work
item lookup remains available.

An authorized reviewer may reopen a mistaken out-of-scope or duplicate
decision with a reason; the prior decision and any former work link remain in
the audit history. Reopening does not change the linked work. Accepted reports
are not reopened through this workflow: staff must resolve any mistake in the
operational work process separately, avoiding accidental creation of duplicate
work.

## Pilot and automation

Before enabling automatic decisions, use approved example scenarios to test
each policy version and compare rule suggestions with reviewer outcomes. Track
abstentions, disagreements, corrections, and scope errors. The deployment's
staff decide whether the results meet their acceptance criteria.

The triage officer approves the operational rubric and pilot. Evaluation must
include both staff-approved representative scenarios and reviewed shadow
reports, with zero observed critical-priority or emergency-urgency under-triage
in the evaluated sample. Zero observed misses alone does not establish safety.
Critical or emergency outcomes, urgent cues, uncertain scope, possible
duplicates, and AI-supported proposals continue to require human review.
Staff must still set minimum sample sizes and acceptable disagreement and
abstention thresholds before any automation is considered.

The shadow summary compares rule proposals with human acceptance decisions,
not with an independently verified ground truth. It separates ambiguous and
conflicting proposals and highlights critical or emergency outcomes missed or
left undetermined by the rules. It does not measure rejected or duplicate
reports as accepted cases, prove scope accuracy, or approve automation.

Until approval and activation, evaluate in shadow mode or send decisions to
human review. If evaluation or policy configuration fails, retain the
submission and route it to review; never silently discard it or default to a
low priority or urgency.

The post-commit callback is not a durable job queue. Before enabling public
reporting, schedule and monitor `python manage.py recover_stalled_triage
--older-than-minutes <age>` with an operationally approved age and frequency.
It retries bounded batches of received reports and routes failed retries to
review; failures of that fallback produce a nonzero exit for alerting. Monitor
the received queue and rerun until the backlog is clear. Scheduling and
alerting must be configured by the deployment; this command alone does not
provide them.

## Interface

The staff review queue should use the deployment's defined theme tokens and
existing interface components wherever appropriate.

## Optional decision-support engine

The triage dashboard is the existing `/review/` queue. Access requires an
employee account and the `review_reportsubmission` permission. It uses the
site's database-backed theme and branding. A reviewer can request an engine
assessment for a report already awaiting review; this never creates work or
changes a confirmed decision.

The mode and complete engine profile are stored in **Site configuration** in
Django Admin. The default is disabled. `Shadow evaluation` records results but
never shows them to reviewers or changes the urgent queue; `Reviewer decision
support` displays results requested in that mode and flags engine safety
escalations for urgent review. Switching modes does not reveal prior shadow
results. The profile is a JSON object in `triage_engine_configuration`; each
job retains its profile snapshot and digest, policy version and input digest.
Changing the profile, active policy, taxonomy or report input invalidates
pending or displayed recommendations. Profile validation by the engine occurs
when the worker processes the request; an invalid profile fails explicitly.

The bundled YAML profiles are **examples**, not approved policy. Administrators
must approve a deployment-specific profile, categories, team routing and
priority definitions against the database's issue taxonomy before enabling
the feature. Engine priorities are not the application's independent priority
and urgency decisions. A current active policy with an unchanged taxonomy is
also required. The engine is advisory even when its own response does not
require review. Its checks are not a substitute for emergency response.

Before enabling it, obtain authorization for sending report descriptions and
location text to the configured AI provider. Free text may contain personal
information. No reporter contact record or photos are deliberately sent, but
they may be mentioned in the description. Assess provider retention, data
residency, contracts, retention of stored results, and access to logs and
backups. Do not place credentials in the database profile.

The service is a separate, authenticated process on the **same isolated host**
as Django. Set the same strong, random `TRIAGE_ENGINE_SERVICE_TOKEN` in both
processes, and set `GEMINI_API_KEY` only for the engine process when authorized.
The token must contain 32–256 letters, digits, `.`, `_`, `~` or `-`. The Django
`TRIAGE_ENGINE_URL` defaults to `http://127.0.0.1:8001`; only an HTTP loopback
address with an explicit port is accepted. Protect the host and its process
environment; loopback and a shared token are not a substitute for isolation
on a shared or untrusted host. Do not expose the engine publicly or use its
unprotected `triage_engine.api:app` entry point.

From `triage_service`, install the locked dependencies and run the authenticated
entry point:

```shell
uv sync --locked
uv run --locked uvicorn triage_engine.secure_api:app --host 127.0.0.1 --port 8001
```

For an example JSON profile to edit and approve, from `triage_service` run:

```shell
uv run --locked python -c "from pathlib import Path; from triage_engine.config_loader import ConfigRegistry; print(ConfigRegistry.from_directory(Path('configs')).get('streetfix').model_dump_json(indent=2))"
```

Paste the approved JSON into Site configuration and choose shadow mode first.
The included example's names, response targets and model choices must not be
assumed appropriate for a deployment. Run `python manage.py migrate`, then
schedule and monitor this bounded worker frequently enough for the agreed
review workflow:

```shell
uv run python manage.py process_triage_engine --limit 20
```

The database stores pending jobs; the worker reclaims leases after five
minutes. Failures are shown to reviewers and return a nonzero command exit;
reviewers may request a new assessment. Provider failures may return a
clearly marked degraded result. Input longer than the engine's limits is
rejected rather than silently shortened. A late result cannot overwrite a
human decision. Monitor queue age, failures and provider costs; turning the
feature off stops new requests and prevents workers from starting jobs.

Give the separate `view_triageenginejob` admin permission only to pilot
evaluators who are not reviewing the same shadow cases. Assessment records,
including shadow results, are read-only in admin and can contain sensitive
report excerpts. Compare shadow results with independently recorded human
decisions and use the pilot safeguards above. Responsible staff must approve
sample sizes and disagreement/abstention thresholds before moving to reviewer
mode. Zero observed critical or emergency misses is necessary in the evaluated
sample but is not proof of safety.

## Public chat, form, maps and photos

The report chat and the report form submit through the same service. Neither
creates work: each saves a report, records the reporter's evidence, and sends it
to central review. The chat's category and priority are only a suggestion made
in the browser; they are stored as an AI-stage triage attempt for the reviewer,
and a reporter's claim that a report duplicates earlier work is stored as
evidence. Only a reviewer links duplicates. The chat accepts a single photo.

The chat lists active, routable issue types from the same taxonomy as the form.
Optional chat categories add keyword suggestions, sub-options and default
priority metadata; they must be linked to a shared issue type. After upgrading,
administrators should use the empty issue-type filter in the chat category
admin to reconcile unlinked legacy categories. The original routing fields are
preserved for reference. Invalid priority codes are reported in application
logs; category priority can be blank for the normal default. Original labels
with matching translations are translated; custom or renamed category and
sub-option labels are not automatically translated.

Every report gets a random reference code that does not reveal how many reports
exist. `INTAKE_REFERENCE_PREFIX` optionally puts a deployment-specific prefix in
front of it. Anyone with a reference can see its progress (received, under
review, or the work's status once accepted), never review decisions or personal
details. The site configuration's separate `reference_prefix` field is not used
for these references; keep `INTAKE_REFERENCE_PREFIX` stable for existing links.

The chat and the rate limits are always on. The form, and photo upload for both,
stay off until a deployment sets the environment variable
`INTAKE_PUBLIC_REPORTING_ENABLED` to `true`. The chat and form link to each
other. Rate limits need a trusted client address, so production settings require
`INTAKE_CLIENT_IP_HEADER`: without it every visitor behind a proxy would share
one limit. Before enabling these features:

- Set `INTAKE_CLIENT_IP_HEADER` to a WSGI `META` key (for example
  `HTTP_X_REAL_IP`) that the hosting edge sets itself and clients cannot forge.
  The default, `REMOTE_ADDR`, is only correct without a reverse proxy. If the
  address is missing or invalid, reports and photo uploads are refused.
- Submissions are limited to 10 per address per hour, and photo upload
  authorizations to 20 per address per hour. Addresses are stored only as keyed
  digests. Schedule `python manage.py prune_rate_limits` regularly to remove
  expired records. Add edge rate limiting as well where the platform offers it;
  Vercel's one-hour edge window requires Enterprise, so the application limits
  matter when the edge uses a shorter window.
- Schedule and monitor `recover_stalled_triage`, as described above.

The location map is optional. It appears only when `INTAKE_MAP_TILE_URL`,
`INTAKE_MAP_ATTRIBUTION`, `INTAKE_MAP_LATITUDE` and `INTAKE_MAP_LONGITUDE`
describe a valid HTTPS tile source; otherwise reporters enter coordinates or
describe the location. Loading tiles shares the visitor's IP address with the
tile provider, so the form says so.

## Report photos

The form may accept up to three optional photos, each no larger than 10 MB, in
JPEG, PNG, WebP or HEIC format. Set `INTAKE_PHOTO_UPLOAD_PRESET` to a *signed*
Cloudinary preset that uses authenticated delivery, does not allow overwrites
and allows caller-supplied public IDs, and configure `CLOUDINARY_URL`. Photos
stay off until both are set.

The browser asks the server for each upload. The server reserves an
unpredictable asset ID bound to the browser session, signs an upload for exactly
that ID, and afterwards fetches the asset's metadata from the provider to verify
its identity, format, size and delivery type. Browser-side limits are not
security controls. An upload failure is shown to the reporter; a report is only
saved with photos that were verified, and never partly attached.

Access to attached photos goes through an authorized application proxy, not a
shareable provider link. Authorized reviewers and employees with an open
assignment to the linked work may view them; access ends when the assignment or
work link ends.

These are implementation requirements, not a claim that deployed streaming,
edge protection or retention of uploaded files have been checked.

Officer photos use the `OFFICER_PHOTO_FOLDER` Cloudinary folder, defaulting to
`work-photos`; set it to the existing folder before deployment if an upload
policy requires the previous path. Already stored photo URLs are unchanged.
Set `GEOCODER_USER_AGENT` to identify the deployment when reverse geocoding.
