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

The review queue and report detail dashboards require both an employee record
and the review permission. Employees with review permission who are not
managers land on the queue after signing in. The queue includes reports still
awaiting processing; its counts cover all pages.

An optional deterministic ReportMatch assessment can be enabled in the
database-backed Site configuration in Django Admin after a deployment
evaluates it. It
only runs when an authorized reviewer requests it on a report in review, and
requires an active policy with both duplicate-search settings and a map pin.
It assesses only the displayed proximity candidates, using the earliest linked
submission's description for each work item; work without a usable original
description is left unassessed. The original submission time is compared with
the new report's time, while candidate search age is based on work creation.
The policy's distance and age are used as matching windows; the detector's
other score thresholds are fixed starting points, not locally validated
probabilities. The detector's bundled English-language text rules may miss
other languages or terminology.

The assessment stays inside the application and does not send data to Gemini.
An append-only triage attempt records the reviewer, engine version, policy,
configuration, candidate IDs, results and truncation. It omits contact details
and photos, although generated signal explanations may contain report text.
Results are not displayed as current if the relevant report, candidate inputs,
policy, or candidate set changes; the reviewer can run them again. Matching
errors are logged and surfaced without preventing manual lookup or review.
Suggested classifications never link work, and related/recurring suggestions
do not create a relationship between work items.

Before enabling it, staff should review representative local examples and
shadow reports, including missed duplicates, different issues at the same
location, recurrences, and incomplete or multilingual descriptions. The
included detector's small sample benchmark does not establish real-world
accuracy. Agree review and monitoring criteria locally and disable the setting
if results are not useful or safe.

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
