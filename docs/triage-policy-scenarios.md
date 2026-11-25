# Triage policy scenarios

These are illustrative framework checks, not an approved policy or a source
of thresholds. Actual issue types, geographic boundaries, mappings, and
acceptance criteria are **[CONFIGURABLE / TENANT-SPECIFIC PENDING]**.

| Scenario | Required behavior |
| --- | --- |
| A report has a selected issue type and sufficient structured evidence under an approved policy. | Evaluate the fields independently, recording the matched conditions and policy version. Automatic finalization remains subject to all intake gates. |
| A report selects Other under a category. | Preserve the selected parent and description; do not invent a specific issue type. Route unresolved classification for review. |
| The description conflicts with the selected type or structured evidence. | Record the conflict and request review rather than silently overriding it. |
| The pin is inside the service area, but ownership is uncertain. | Do not infer responsibility from the pin alone. Request human review. |
| A pin is missing or unreliable. | Preserve the submission and allow a reviewer to correct the location with a reason. Do not create a new work item until a reliable location is resolved. |
| Evidence of sensitive content is reported for a relevant issue type. | Apply only the approved priority modifier; do not change urgency without separate time-sensitivity or safety evidence. |
| A report indicates immediate danger. | Flag it for the urgent human queue. The app does not promise immediate response. |
| An active work item may describe the same issue. | Present a candidate to a reviewer. Link only after human confirmation. |
| A similar work item is closed or cancelled. | Show it as context; a recurrence requires a new work item rather than reopening the terminal item. |
| A report appears outside the deployment's responsibility. | Preserve the submission and require a human to approve any out-of-scope rejection. |
| No approved policy applies, evaluation fails, or conditions conflict. | Abstain and route to human review; do not infer a low-risk result. |

Staff must supply and approve deployment-specific examples before enabling
automatic priority or urgency decisions. Pilot results and policy changes must
be reviewed against those examples before activating a version.
