# StreetFix Configurability Implementation Plan

## Goal

Make operational taxonomy, workflow semantics, presentation, translations, and organisation-specific rules configurable in the database while retaining secrets and deployment infrastructure in environment/Django settings.

This plan implements the findings in `CONFIGURABILITY_AUDIT.md` in reviewable stages. It does not prescribe a single large migration or a complete UI rewrite.

## Completion Criteria

The implementation is complete when:

- An administrator can change active issue categories, subcategories, departments, priorities, urgencies, statuses, outcomes, contact methods, languages, navigation, and theme without source changes.
- Lifecycle behavior is driven by database semantics and transition policies, not comparisons with status/outcome code strings.
- The public chat, staff UI, API, forms, templates, JavaScript, CSS, reports, and maps consume the same database configuration.
- Labels and copy can be localized from database-backed content.
- Operational thresholds and SLA/duplicate/travel/photo policies are database-configurable.
- Referenced configuration cannot be deleted accidentally and historical work remains readable.
- Missing or inactive configuration fails safely with validated fallbacks.
- Existing seed data is migrated and existing reports/work items remain valid.
- The full test, lint, formatting, type-check, migration, and collectstatic checks pass.

## Implementation Principles

1. Prefer semantic flags and policy relations over code-string comparisons.
2. Keep immutable machine keys only for stable integration contracts; make display labels and behavior mutable.
3. Make configuration rows active/retirable instead of deleting them.
4. Seed all existing behavior as defaults during migrations.
5. Centralize browser and server configuration in database-backed APIs/models.
6. Use transactional migrations and reversible seed/rollback operations.
7. Cache expensive configuration, with admin-save and migration invalidation.
8. Preserve safe environment-only settings for secrets and infrastructure.
9. Add focused tests at each phase rather than delaying validation until the end.

## Phase 0: Baseline and Cross-Cutting Foundation

### Work

- Establish a `configurability` or shared configuration app/model naming convention.
- Define stable machine-key, label, active, sort-order, locale, description/help-text, and audit conventions.
- Define a singleton `SiteConfiguration` pattern for organization-wide settings.
- Add configuration helpers for:
  - cached singleton access;
  - active rows;
  - safe label lookup;
  - localized content lookup;
  - system-key fallback;
  - cache invalidation.
- Define deactivation and replacement rules for referenced rows.
- Add database audit history if configuration-change accountability is required.
- Document the boundary between database configuration and environment-only infrastructure.

### Acceptance Tests

- A missing singleton falls back safely.
- Invalid or missing translations fall back predictably.
- Deactivating a row prevents it being offered in new workflows.
- Historical records continue to resolve deactivated labels.
- Configuration changes invalidate cached values.

## Phase 1: Lookup and Lifecycle Semantics

### Models

Extend existing lookup models rather than introducing duplicate lookup systems.

#### Priority

Add or normalize:

- active flag;
- sort/rank;
- colour/style key;
- icon;
- urgent flag;
- optional acknowledgement SLA;
- optional resolution SLA.

#### Urgency

Add or normalize:

- active flag;
- sort/rank;
- emergency flag;
- icon/style key.

#### WorkItemStatus

Add:

- active flag;
- sort/rank;
- ended flag;
- paused flag;
- submitted/not-triaged flag;
- dispatchable flag;
- officer-active flag;
- awaiting-review flag;
- resolved flag;
- cancelled flag;
- style key.

#### WorkStatusTransition

Add allowed transitions with:

- source status;
- target status;
- action/event key;
- allowed role/permission;
- required fields;
- side-effect policy;
- active flag.

#### CancellationReason

Add:

- active flag;
- sort order;
- notes-required flag;
- special system key if used by policy only.

### Code Changes

- Replace direct code comparisons in work models, dispatch, field work, approval, overview, and officer views with status flags or transition policies.
- Replace `PRIORITY_RANK` and `URGENCY_RANK` dictionaries with database ranks.
- Replace hard-coded urgent `CRITICAL`/`EMERGENCY` checks with semantic flags.
- Move cancellation validation and end-time behavior to status semantics.
- Replace status/priority hard-coded chips and map colours with database style keys/colours.
- Retain an integration migration only for old machine keys.

### Acceptance Tests

- Rename and reorder priorities and urgencies; sorting and urgent counts use database values.
- Reclassify a status by changing semantic flags; dispatch, dashboards, and field workflows respond without code changes.
- Create, disable, and re-enable lifecycle statuses.
- Reject transitions not declared in `WorkStatusTransition`.
- Verify all existing status/outcome/cancellation seed data migrates unchanged.
- Verify no direct production code still compares status/outcome codes for behavior.

## Phase 2: Issue Taxonomy and Intake Routing

### Models

Add:

- `IssueCategory`;
- `IssueCategorySubcategory`;
- `IssueCategoryKeyword` or keyword/rule policy;
- category-to-issue-type routing;
- category default priority/urgency;
- category team/department routing;
- active and sort fields.

Suggested fields:

- machine key;
- label/help text;
- department and issue-type foreign keys;
- default priority and urgency foreign keys;
- icon/style key;
- keyword rules;
- priority raise policy;
- active and sort order.

### Code Changes

- Remove `ISSUE_TYPES`, `PRIORITY_CODES`, `URGENCY_CODES`, and `CONTACT_CODES` dictionaries from Python.
- Remove `_issue_type()` automatic creation behavior.
- Make report parsing read category, subcategory, priority, urgency, and contact values from database rows.
- Add an API endpoint or bootstrap payload for active categories, subcategories, labels, and routing metadata.
- Make the public chat initialize from the same payload instead of `CATS`, `SUBS`, and category keyword dictionaries.
- Add server-side validation that category/subcategory/contact values are active and valid.
- Map reporter urgency and issue priority through database relationships or explicit policy rows.

### Acceptance Tests

- Add a category and subcategory in Admin; it appears in the public chat/API and creates the intended database issue type.
- Rename/disable/reorder categories; browser and server behavior stay aligned.
- Disable a category while retaining historical reports.
- Invalid category, subcategory, priority, urgency, or contact values are rejected.
- Existing seeded categories continue to create the same issue types and work items.

## Phase 3: Visit Outcomes and Field-Work Configuration

### Models

Add or replace `TextChoices` with database models:

- `VisitOutcome`;
- `PhotoTag`;
- `FurtherWorkReason`;
- `Hazard`;
- `VisitConfirmation`;
- `AssignmentRole`;
- generic report-answer/conditional-option definitions where useful.

Store on each model:

- machine key;
- label/help text;
- active and sort fields;
- target status relation;
- further-work required flag;
- unfinished flag;
- notes/photo requirements;
- locale-aware copy.

Move existing visit constants into seed migrations:

- fixed/temporary/further/no-access/no-fault outcomes;
- before/after photo tags;
- further-work reasons;
- hazards;
- confirmations;
- yes/no labels;
- role labels and placeholders.

### Code Changes

- Remove `WorkItemReport.Outcome`, `WorkItemPhoto.Tag`, `FURTHER_REASONS`, `HAZARDS`, and `CONFIRMATIONS` as behavioral sources.
- Replace outcome sets with fields/policies on `VisitOutcome`.
- Replace outcome-to-status mappings with transition/policy records.
- Make form choices active database rows.
- Replace minimum lengths and photo-exception thresholds with field operations policy.
- Replace assignment role choices and placeholders with database content.

### Acceptance Tests

- Add/rename/disable outcomes and report options.
- Change outcome target status and verify the field-work submission follows the new status.
- Configure further-work and unfinished semantics.
- Change no-photo requirements and minimum text lengths consistently across form and server.
- Verify existing outcome/photo/tag values remain readable after migration.

## Phase 4: Operational Policy Configuration

### Models

Add:

- `SlaPolicy`;
- `DuplicatePolicy`;
- `FieldOperationsPolicy`;
- `PhotoPolicy`;
- `ReferenceFormatPolicy`;
- text-quality/validation policy tables where needed.

Suggested settings:

- SLA acknowledgement/resolution durations by priority/urgency/category/team;
- working-day and timezone behavior;
- duplicate radius and time window;
- field depot name/coordinates;
- average speed, road factor, on-site duration;
- geocoder and map policy;
- postcode and address rules;
- photo size/count/type limits;
- cache TTL;
- reference prefix/pattern;
- waiting-too-long threshold;
- progress stage thresholds.

### Code Changes

- Remove fixed duplicate radius/window, reference prefix, travel speed/factor/on-site minutes, waiting thresholds, and photo limits.
- Move Nominatim/postcodes.io feature enablement and provider policy to configuration while keeping credentials and URLs/provider infrastructure environment-controlled.
- Make chat SLA messages and staff workflow calculations use the same database policies.
- Implement configuration validation and safe defaults.

### Acceptance Tests

- Change duplicate radius/window and verify matching behavior.
- Change depot coordinates and verify planning and fallback maps.
- Change SLA values and verify server/API/chat target dates agree.
- Change travel assumptions and verify plan estimates.
- Change photo size/type limits consistently across browser and server.
- Verify invalid policy combinations are rejected.

## Phase 5: Theme, UIkit, CSS, and Media

### Models

Extend `ThemeSettings` or add `DesignToken`.

Cover:

- all static CSS colours;
- surfaces/elevations;
- borders and line colours;
- text emphasis/muted/disabled/focus states;
- primary/secondary/success/warning/danger states;
- status and priority presentation;
- map depot/route/marker colours;
- radius, spacing, breakpoints, density, typography, shadow, border width, icon set, and motion.

### Code Changes

- Replace hard-coded CSS fallbacks that control application UI with database-generated CSS variables.
- Remove or minimize static secondary palettes that disagree with `ThemeSettings`.
- Replace priority/status template-tag dictionaries with database values/style keys.
- Replace JavaScript map and pin colours with API/context theme variables.
- Provide explicit theme variables for all custom CSS components.
- Include theme admin preview and contrast validation for every text/background pairing.
- Add database-driven favicon and brand icon configuration if not already complete.

### Acceptance Tests

- Change every theme token and verify public, staff, mobile, chat, reports, analytics, and error surfaces.
- Verify contrast validation applies to status, map, muted text, and optional overrides.
- Verify missing optional theme values derive correctly.
- Verify CSS, inline styles, JavaScript map colors, and template tags do not use conflicting literals.

## Phase 6: Localized Content and Navigation

### Models

Add:

- `SupportedLanguage`;
- `LocalizedContent`;
- `NavigationEntry`;
- `ApplicationModule`;
- `ErrorContent`;
- optional `PageSection`/`Widget` configuration.

Store:

- language code, locale, direction, native label, default/active;
- entity/key/locale/value for copy;
- route name, label, icon, permission/role, active/sort for navigation;
- status code, title, message for errors.

### Code Changes

- Move chat language dictionaries into database-backed API/bootstrap configuration.
- Move category, subcategory, priority, urgency, and status labels out of JavaScript and templates where user configuration is intended.
- Replace template navigation copy and links with active `NavigationEntry` rows.
- Move shared page titles, descriptions, headings, actions, empty states, errors, confirmations, and footers into localized content.
- Integrate Django validation/error/form copy with localization.
- Add localized allauth/account content only where it should vary by organisation.
- Add language context and RTL support at all template/JavaScript surfaces.

### Acceptance Tests

- Add a language and locale; public chat, UI direction, and date formatting follow it.
- Rename shared navigation and page copy; no source/template edit is needed.
- Change each active language; Django, chat, forms, and API copy agree.
- Missing translation falls back to the configured default language.
- RTL layout works with database direction.

## Phase 7: Authentication, Routes, and Feature Policy

### Scope

This phase should separate technical routing/security from configurable organisation policy.

### Work

- Add database-backed application/module enablement and navigation.
- Make public/staff feature exposure configurable where compatible with route security.
- Make non-security authentication policy database-configurable:
  - signup enabled;
  - login identifier/method;
  - verification requirement;
  - login/logout redirects;
  - account labels.
- Keep middleware, auth backends, secret keys, cookie security, allowed hosts, CSRF settings, and credentials environment/Django settings.
- If public route policy is dynamic, add role/route authorization policy that is validated at startup and enforced server-side.

### Acceptance Tests

- Disable a module and verify navigation/API/routes are unavailable when intended.
- Change redirects and public/auth copy.
- Signup/verification policy changes take effect without route or middleware changes.
- Security-critical environment settings remain environment-controlled.
- Anonymous and staff access are denied/allowed consistently.

## Phase 8: Data Migration and Deployment Safety

### Migration Plan

1. Add fields and new models with defaults/nulls.
2. Populate existing seed values and expected machine keys.
3. Backfill all current work items/reports with existing semantics.
4. Add constraints after backfill.
5. Switch application reads/writes to database models.
6. Remove or isolate obsolete code dictionaries after tests pass.
7. Provide reverse migration where possible without deleting historical configuration or work.

### Seed Data

Maintain initial data migration or post-migrate data for:

- default theme and site settings;
- departments/issue types;
- priorities/urgencies/statuses/cancellation reasons;
- contact methods;
- outcomes/photo tags;
- languages;
- navigation;
- field/deployment policy;
- SLA/duplicate/travel defaults;
- core localized content.

### Safe Defaults

Implement:

- singleton missing-row behavior;
- inactive-row handling;
- missing locale fallback;
- missing transition policy rejection or explicit safe fallback;
- missing issue routing/admin-visible error rather than silent wrong department/type;
- fallback theme variables without invalid CSS;
- migration-time backfills that do not overwrite administrator edits.

## Phase 9: Test, Quality, and Observability

### Test Categories

- model constraints and semantic validation;
- migrations and reversibility;
- configuration admin behavior;
- public chat/API taxonomy and localization;
- lifecycle transitions and domain invariants;
- status/priority/urgency filtering and dashboards;
- field reports and outcomes;
- duplicate/SLA/travel/photo behavior;
- theme rendering across public/staff/mobile surfaces;
- navigation and feature enablement;
- authorization and public route policy;
- cache invalidation;
- missing/inactive configuration fallbacks.

### Quality Checks

Run from the repository root:

```shell
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run python manage.py collectstatic --noinput
uv run pre-commit run --all-files
```

Add new migration, browser/API, and model tests to existing test folders. Do not treat migration-only success or seed row creation as sufficient verification.

### Observability

Add logs/diagnostics for:

- missing configuration;
- invalid policy combinations;
- fallback locale/theme/content usage;
- missing issue routing;
- cache invalidation failures;
- external geocoder/provider failures.

Keep public error copy localized and user-safe; keep diagnostic details in server logs.

## Suggested Delivery Sequence

1. Foundation and lifecycle semantics.
2. Lookup maturity and migration-safe defaults.
3. Issue taxonomy and public chat API.
4. Field-report outcomes and operational policy.
5. Theme/design tokens and UI surfaces.
6. Localized content/navigation.
7. Authentication/routes/module policy.
8. Audit history, observability, and final cleanup.

Each stage should be a separate branch/PR where practical, with existing behavior preserved until configuration has full test coverage.

## Out of Scope

Keep these environment-only or technical:

- Django secret key;
- database credentials and connection URL;
- Cloudinary/provider credentials and API tokens;
- allowed hosts/CSRF infrastructure;
- middleware and Django app installation;
- static manifest and storage backend implementation;
- security cookie flags;
- application URL implementation;
- test/development/production mode selection.
