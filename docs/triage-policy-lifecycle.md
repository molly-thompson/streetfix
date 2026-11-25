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
