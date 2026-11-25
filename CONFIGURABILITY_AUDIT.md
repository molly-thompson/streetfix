# StreetFix Configurability Audit

**Audit branch:** `refactor/configurability`
**Branch base:** `main` at merge commit `a2e6441`
**Scope:** Django models, migrations, settings, views, forms, templates, static CSS/JavaScript, seed data, and tests on `main`
**Audit type:** read-only findings only; no application behavior or schema was changed

## Executive Summary

StreetFix already has useful database-backed configuration for some site branding and several operational lookup values, but it is not yet entirely configurable from the database. The remaining configuration is distributed across Python constants, Django `TextChoices`, migration seed rows, JavaScript dictionaries, CSS defaults, HTML copy, and Django settings.

The largest gaps are:

1. **Public chat taxonomy and workflow copy:** issue categories, sub-issues, team names, priority/urgency mappings, translations, hazard phrases, SLA targets, and sample cases are hard-coded.
2. **Lifecycle semantics:** status and outcome codes are embedded in Python conditions. Database labels alone are not enough to change lifecycle behavior.
3. **Operational rules:** ranking, pause/ended/active status groups, duplicate detection, travel estimates, photo rules, and outcome transitions are fixed in code.
4. **UI theming:** CSS still has substantial hard-coded colors and typography, while JavaScript also contains hard-coded map colors and UI language. Some values are already exposed through `ThemeSettings`, but this is not complete.
5. **Visible copy and navigation:** page titles, labels, explanatory text, error text, action names, authentication text, and all/navigation labels are hard-coded in templates, Python, and JavaScript.
6. **Deployment and integration settings:** field-depot geography, geocoding/storage providers, paths, URLs, authentication policy, locale, timezone, and infrastructure features are still settings/environment-driven.

The recommended end state is a small set of database configuration models plus clearly separated immutable technical settings. “Entirely configurable via the database” should not mean moving secrets or process-level Django infrastructure into application tables; it should mean moving tenant/organisation, domain, lifecycle, copy, taxonomy, workflow, and presentational behavior into database-backed models, while retaining secrets and connection infrastructure in environment variables.

## Already Configurable

The following areas provide a good base and should be preserved.

- `ThemeSettings` is a singleton containing site name, favicon, navbar icon, core theme colors, radius, and optional semantic colors.
- `Department`, `IssueType`, `Priority`, `Urgency`, `WorkItemStatus`, and `CancellationReason` are database models.
- `Priority`, `Urgency`, `WorkItemStatus`, and `CancellationReason` are administrator-editable labels in Django Admin; codes remain fixed.
- `ContactMethod` is a database lookup with administrator-editable labels.
- Priority guidance and urgency guidance are database fields.
- Issue types and departments are administrator-created data rather than hard-coded in the model layer.
- Most work items already reference lookup rows using foreign keys rather than storing display labels.

## Findings

### 1. Public chat category taxonomy

**Priority: critical**

**Evidence**

- `intake/chat.py`: `ISSUE_TYPES` maps public category keys to department names, issue-type codes, and display names.
- `intake/chat.py`: `_issue_type()` uses `get_or_create()` to create departments and issue types from the mapping.
- `static/js/report-chat.js`: `CATS`, `SUBS`, `KEYWORDS`, and category/team defaults duplicate the server-side taxonomy.
- `static/js/report-chat-i18n.js`: category and sub-issue labels are embedded in all supported language dictionaries.
- `intake/views.py` and `intake/chat.py` accept category keys and translate them into database issue types.

**Impact**

Adding, renaming, disabling, reordering, recategorizing, or translating an issue category requires changes to Python and JavaScript. Public category keys and server taxonomy can drift.

**Required refactor**

- Add database models for report categories, category sub-issues, category keyword rules, and category/team routing.
- Category/sub-issue rows need code/key, label, description, sort order, active flag, department/issue-type foreign key, default priority, and optional icon.
- Server and browser must load the same active category/sub-issue configuration; do not maintain duplicate mappings.
- Remove `_issue_type()`’s automatic department/issue-type creation behavior. Category configuration should reference existing database rows explicitly.
- Add category localization in a database-backed translation model or a separate translatable fields model.

### 2. Priority and urgency are not semantically configurable

**Priority: critical**

**Evidence**

- `employees/work_models.py` stores `Priority` and `Urgency` lookup rows.
- `employees/dispatch.py`: `PRIORITY_RANK` and `URGENCY_RANK` hard-code codes and order.
- `intake/chat.py`: `PRIORITY_CODES`, `URGENCY_CODES`, `SLA`, and chat defaults map names to fixed codes.
- `employees/overview.py`: `CRITICAL` and `EMERGENCY` are hard-coded as urgent conditions.
- `employees/templatetags/fieldops.py`: priority codes are mapped to hard-coded colors.
- `employees/officer_views.py`: priority codes are mapped to hard-coded map pin colors.
- `employees/migrations/0002_seed_work_options.py` fixes all priority, urgency, status, and cancellation codes and defaults.

**Impact**

Labels can change, but priority rank, urgency rank, urgent business rules, default mappings, SLA tiers, and colors cannot be changed safely.

**Required refactor**

- Extend `Priority` with rank, colour, icon, active flag, sort order, and acknowledgement/resolution SLA values or replace separate SLA tables.
- Extend `Urgency` with rank, active flag, and sort order.
- Store chat priority/urgency names or keys as foreign/normalized mappings rather than dictionaries keyed by English display text.
- Replace code checks such as `CRITICAL`, `EMERGENCY`, and the fixed rank dictionaries with database ordering/flags (for example `is_urgent`, `is_emergency`, or configurable rank).
- Add database-backed CSS/style keys and colors for priority and status presentation.

### 3. Work-item lifecycle is hard-coded

**Priority: critical**

**Evidence**

- `employees/work_models.py`: `WorkItem.clean()`, `transition_to()`, end-state behavior, and cancellation rules check `"CLOSED"`, `"CANCELLED"`, and `"OTHER"` by code.
- `employees/dispatch.py`: ended, submitted, triaged, and assigned codes are tuples or direct string checks.
- `employees/field_work.py`: active states, arrival, start-work, and visit outcome mappings are fixed.
- `employees/approval.py`: awaiting approval is fixed to `"RESOLVED"`, and send-back targets `"IN_PROGRESS"`; close targets `"CLOSED"`.
- `employees/overview.py`: paused, ended, stage, and in-progress codes are fixed.
- `employees/visit_report.py`: outcome groups are Python sets.
- `employees/templatetags/fieldops.py`: status codes map to stylesheet names.

**Impact**

The application cannot add, rename, disable, or reorder lifecycle stages without editing code and migrations. Lifecycle is split across multiple independent constant sets.

**Required refactor**

- Extend `WorkItemStatus` with semantics: active/ended, not-yet-triaged, dispatchable, officer-active, awaiting-review, paused, resolved, default-end-date behavior, sort order, and UI style key.
- Add allowed status transitions and transition side effects in database models or a policy table. Include closure, reopening, cancellation, assignment/removal, approval, and send-back behavior.
- Add database-backed cancellation policies. `OTHER` and “notes required” should be fields/relations, not code special cases.
- Move visit outcome behavior to database models/lookup rows or a typed outcome policy relation. An outcome should define target status, whether further work is required, and whether work is considered unfinished.
- Replace all code comparisons with semantic flags or relations.

### 4. Work outcome, photo, and field-report configuration

**Priority: high**

**Evidence**

- `employees/work_models.py`: `WorkItemReport.Outcome` and `WorkItemPhoto.Tag` are Django `TextChoices`.
- `employees/migrations/0005_work_item_report.py` duplicates outcome and tag choices.
- `employees/visit_report.py` hard-codes further-work reasons, hazards, confirmations, yes/no choices, minimum lengths, and outcome behavior.
- `employees/field_work.py` hard-codes 15-character minimum for missing before-photo explanations and before-photo requirements.
- `employees/forms.py` hard-codes assignment roles and example placeholder copy.

**Impact**

Report forms, outcomes, safety lists, confirmation statements, and role labels cannot be maintained without code/deployment changes.

**Required refactor**

- Add database models for report outcomes, photo types/tags, further-work reasons, hazards, confirmations, and assignment roles.
- Add translatable label/help text, active flag, sort order, and conditional requirements.
- Add outcome fields for further-work, no-access, and unfinished semantics.
- Move form validation thresholds and no-photo/photo requirements into configuration.
- Replace `TextChoices` and JSON free-form extra answers with schema-backed report answer definitions where practical.

### 5. SLA and routing rules

**Priority: high**

**Evidence**

- `intake/chat.py`: SLA acknowledgement and resolution times are hard-coded in JavaScript `SLA`.
- `static/js/report-chat-i18n.js`: acknowledgement and fix-target copy is hard-coded.
- `intake/chat.py`: duplicate radius and duplicate window are constants.
- `employees/geo.py`: depot and travel assumptions are settings/constants.
- `config/settings/base.py`: field depot, postcode lookup, reverse geocoding, and photo cloudinary mode are settings.

**Impact**

Service targets, duplicate matching, travel planning, geocoding, and postcode behavior vary only through code/environment and cannot be changed by an administrator.

**Required refactor**

- Add database-backed SLA rules per priority/urgency, team, issue category, and possibly calendar.
- Add configurable acknowledgement and resolution durations, working-day behavior, holiday calendar, and timezone.
- Add duplicate-detection policy with radius, time window, issue-category scope, and location fallback.
- Move depot location and name into database geography settings.
- Move travel speed, road factor, and on-site minutes into database planning settings.
- Keep provider endpoints and credentials in environment; expose feature enablement and provider policy through database settings where appropriate.

### 6. Contact methods and public reporter configuration

**Priority: medium**

**Evidence**

- `intake/models.py` has database-backed `ContactMethod`.
- `intake/chat.py`: `CONTACT_CODES`, English contact names, and text/phone/email routing are hard-coded.
- `intake/migrations/0002_seed_contact_methods.py` seeds fixed codes.
- `static/js/report-chat.js`: `METHODS` only supports Email, Text message, and Phone call.
- `intake/chat.py` and submission logic contain code-specific TELEPHONE/EMAIL assumptions.

**Impact**

Changing or extending contact methods requires code and UI updates.

**Required refactor**

- Let contact methods be first-class database rows with channel type, validator, label, order, active flag, and update-routing handler.
- Replace `CONTACT_CODES` and fixed UI methods with database data.
- Add database-backed validation and consent text per channel.

### 7. Chat languages and translations

**Priority: high**

**Evidence**

- `static/js/report-chat-i18n.js` contains six complete language dictionaries and English fallback strings.
- `static/js/report-chat.js` hard-codes language codes, locale codes, RTL languages, language names, and stage copy.
- Django templates also contain English copy; server and browser do not share an internationalization source.
- `config/settings/base.py` fixes `LANGUAGE_CODE`, `TIME_ZONE`, and i18n settings.

**Impact**

Languages, RTL behavior, locale IDs, wording, and fallback language cannot be maintained in the database or changed independently.

**Required refactor**

- Add database-backed supported-language rows with code, locale, direction, label, default flag, and active flag.
- Move user-facing message/translation keys into translatable database records or an application content system backed by the database.
- Use the same localization catalog for templates, Python validation text, and JavaScript.
- Do not leave English strings and third-language translations split across static files.

### 8. Theme is only partially dynamic

**Priority: critical**

**Evidence**

- `site_settings/models.py` has database-backed core and optional theme fields.
- `site_settings/context_processors.py` exposes theme variables to templates.
- `static/css/theme.css` has hard-coded default/fallback colors, backgrounds, shadows, border radii, font/color states, and UIkit overrides.
- `static/css/fieldops.css`, `static/css/fieldops-mobile.css`, and `fieldops-mobile-extras.css` define a second palette with hard-coded root variables and many literals.
- `static/css/report-chat.css` mixes database CSS variables with literals.
- `templates/` contain inline style values and UIkit utility classes.
- `static/js/report-chat.js` and `static/js/officer.js` contain hard-coded map/pin colors.
- `Priority` and `WorkItemStatus` UI colors/styles live in `employees/templatetags/fieldops.py`.

**Impact**

The application can change a subset of theme tokens, but several UI surfaces, field colors, status styles, map icons, shadows, and legacy CSS defaults do not follow the singleton settings.

**Required refactor**

- Complete `ThemeSettings` into a comprehensive design-token model or related token table.
- Include surface/elevation, line, disabled state, focus, overlays, typography, spacing, border radius, icon, status, priority, and map colors.
- Remove literal core UI colors from all CSS; retain only generated fallback values outside runtime.
- Move priority/status/role colors and status CSS keys into database models.
- Move map marker, route, depot, and tile styling from Python/JavaScript into theme/geographic configuration.
- Include UI kit and admin styling or provide a database-to-admin-theme mechanism.
- Audit inline styles and template utility classes for organization-specific colors.

### 9. Global UI copy and navigation

**Priority: high**

**Evidence**

- `templates/base.html` hard-codes Intake, Employees, Analytics, copyright copy, and page description.
- `templates/employees/` and `templates/intake/` contain extensive hard-coded headings, labels, explanations, confirmations, and actions.
- `templates/account/` and `templates/allauth/` contain framework and authentication copy.
- `config/error_handlers.py` contains titles and messages.
- Python form widgets contain placeholders and validation messages.
- JavaScript i18n data contains complete customer-facing copy.

**Impact**

Brand/site copy, terminology, navigation names, error copy, and workflow wording cannot be changed centrally.

**Required refactor**

- Add database-backed application copy/content keys for shared navigation, titles, descriptions, labels, empty states, errors, notifications, confirmations, and footer text.
- Integrate the Django template, form, view, error-handler, and JavaScript text systems around one localization/content mechanism.
- Make navigation entries/database-configurable rather than hard-coded in `base.html`.
- Move allauth/account copy and login/signup restrictions into database or overridable template/content settings where appropriate.

### 10. Routes, section names, and application feature exposure

**Priority: medium**

**Evidence**

- `templates/base.html` exposes Intake, Employees, and Analytics as fixed links.
- `config/urls.py` installs fixed top-level paths and fixed Django-allauth/admin routes.
- `employees/urls.py` and `intake/urls.py` use fixed application routes.
- Feature modules are installed in `INSTALLED_APPS` statically.
- Analytics is an application shell with fixed overview copy.

**Impact**

Enabling/disabling modules, renaming sections, customizing navigation order, or changing public routes is not data-driven.

**Required refactor**

- Add database-backed navigation/module configuration with route name, label, icon, required permission/department, active flag, and sort order.
- Decide whether top-level routes and module enablement remain deployment-level technical settings. If they must be user-configurable, add a routing/service registry model and startup-safe routing behavior.
- Add database-backed dashboard/widget configuration for analytics and manager views.

### 11. Authentication and public access policy

**Priority: medium, but security-sensitive**

**Evidence**

- `config/settings/base.py` fixes login methods, signup fields, mandatory email verification, login/logout redirect URLs, adapter, public paths, and auth middleware.
- `config/adapters.py` has no-signup behavior.
- Public paths and staff areas are enforced by code/middleware/route structure.
- `NoSignupAccountAdapter` disables sign-up via code.

**Impact**

Authentication, registration, verification, redirects, and public-route policy require deployment/code changes.

**Required refactor**

- Keep secrets, backends, middleware, and security protections in Django settings, but make non-security policy database-configurable where appropriate: signup enabled, login method, verification policy, redirects, public route policy, and account labels.
- Add explicit authorization policy objects rather than route-name lists if public/staff policy is expected to vary.
- Store policy in a singleton or configuration table with caching and fail-safe secure defaults.

### 12. Geography and external integration configuration

**Priority: high**

**Evidence**

- `FIELD_DEPOT` contains the fixed depot name and coordinates.
- `REVERSE_GEOCODING`, geocoder user agent, Nominatim URL, postcodes.io URL, and cache duration are code/settings.
- Cloudinary selection is derived from environment.
- `OFFICER_PHOTOS_ON_CLOUDINARY` and storage backends are settings/environment.
- `static/js/officer.js` and officer views hard-code OpenStreetMap tile URLs.
- `geo.py` hard-codes postal/address formatting and cache behavior.

**Impact**

Deployments cannot change region, map provider, depot, geocoding policy, postcode provider, storage, or street-address formatting through normal application data.

**Required refactor**

- Add database organization/geography settings for country/region, postcode format, depot, map bounds, map provider, tile endpoint, reverse geocoder, address format, and fallback coordinates.
- Add provider configuration and secrets separation for Cloudinary/storage/geocoders.
- Move photo limits, accepted MIME types, cache TTL, and storage folder policies into database configuration.

### 13. Operational constants and thresholds

**Priority: medium/high**

**Evidence**

- Photo limits: `MAX_PHOTO_BYTES`, 40 MB and 15-character limits appear across Python/JavaScript.
- `DUPLICATE_RADIUS_KM`, duplicate window, postcode cache, and geocoding cache behavior are constants.
- Travel speed, road factor, and on-site minutes are constants.
- Waiting-too-long is seven days.
- Workday response calculations and acknowledgement targets are JavaScript constants.
- `VAGUE_WORK` and vague-work validation regex are code constants.
- Reference prefix is fixed to `SF-`.
- UI stage numbering and progress values are code-driven.

**Impact**

Operational thresholds vary only via code changes and are easy to make inconsistent between UI and backend.

**Required refactor**

- Create database-backed policy settings with code to read the same values for validation, UI, scheduling, and API.
- Include limits for photo size/count/type, postcode acceptance, duplicate detection, waiting thresholds, travel estimates, text-quality checks, reference format, and chat stage configuration.
- Keep technical regex implementation configurable in data only where organizationally meaningful; otherwise provide named policy types.

### 14. Fixed status code assumptions across models and queries

**Priority: critical**

**Evidence**

- Direct code comparisons exist in `chat.py`, `dispatch.py`, `field_work.py`, `approval.py`, `overview.py`, `work_models.py`, and officer views.
- Direct code filters exist for priorities, urgencies, statuses, issue types, and ended/paused states.
- Tests rely heavily on seed code values.

**Impact**

Changing a status code or lifecycle label can break behavior even if the database row exists. Fixed code IDs are also coupled to chat, status history, forms, and reports.

**Required refactor**

- Separate immutable system keys from mutable labels and semantics.
- Implement database semantics (`is_ended`, `is_paused`, `is_active`, `is_triaged`, `is_resolved`, `is_cancelled`, `can_dispatch`, `can_accept_arrival`, `can_submit_report`) rather than comparing codes in application logic.
- Preserve system keys only where they act as stable integration contracts, and document them.
- Permit admin to add/remove/disable rows without breaking lifecycle transitions.

### 15. Admin restrictions and lookup editability

**Priority: medium**

**Evidence**

- `FixedOptionAdmin` prevents adding/deleting priority, urgency, status, and cancellation rows.
- `ContactMethodAdmin` prevents adding/deleting contact methods.
- Lookup codes are `editable=False`, while labels are editable.
- There are no active, sort, icon, colour, translation, or deprecation fields.

**Impact**

Administrators can rename values but cannot add, retire, reorder, localize, or safely extend domain sets.

**Required refactor**

- Replace “fixed/no add/delete” lookup behavior with active/archive fields and migration-safe keys.
- Allow additions when code-specific integration behavior is avoided or when a policy relation is added.
- Add admin guards for immutable in-use rows or provide replacement/deprecation workflows.
- Enforce referential integrity and prevent deletion of referenced lookup values.

### 16. Error handling and HTTP copy

**Priority: medium**

**Evidence**

- `config/error_handlers.py` defines titles and messages in `ERROR_CONFIG`.
- `templates/error.html` displays code/title/message.
- Validation and permission messages are scattered through domain modules.

**Impact**

Error copy and status presentation cannot be localized or configured centrally.

**Required refactor**

- Add database-backed status/error content keyed by machine code and locale.
- Preserve safe internal logging/diagnostic context separately from public copy.
- Unify Django form, API, and template error formatting.

### 17. Hard-coded UI symbols and structure

**Priority: low/medium**

**Evidence**

- Navbar brand icon values and UIkit icon names are database choices or template literals.
- The report chat uses camera, close, and accordion UIkit icons.
- Officer navigation, steps, and stage labels are template code.
- CSS layout dimensions, breakpoints, border widths, shadows, spacing, and animation durations are static.

**Impact**

Organizations cannot completely restyle structure or iconography.

**Required refactor**

- Add theme/layout settings for icon set, icon mapping, spacing, breakpoints, elevation, border widths, motion, and density.
- Model officer workflow steps as configurable workflow steps rather than `OFFICER_STEPS`.
- Model navigation labels/icons/order/permissions.

## Data Model Recommendations

The following are proposed areas for future implementation. Names are suggestions, not implementation.

1. **SiteConfiguration** (singleton)
   - Branding, locale, timezone, country/region, navigation, footer, feature flags, geography, provider-policy references.

2. **ThemeSettings / DesignToken**
   - Existing singleton can remain; add token/category/key/label, or add explicit fields for all static CSS concepts.

3. **Department**
   - Add code, active, sort order, icon, description.

4. **IssueCategory / IssueSubcategory**
   - Code/key, department/issue-type routing, label/help text, default priority/urgency, keywords, active, sort order, icon/style.

5. **IssueCategoryTranslation / ContentTranslation**
   - Entity type/entity ID/key/locale/value.

6. **Priority / Urgency**
   - Rank, active, sort order, semantic urgent flags, icon/colour, SLA relation.

7. **WorkItemStatus**
   - Semantic flags, rank, style key, allowed transition relations, active flag.

8. **WorkStatusTransition**
   - From status, to status, event/action key, allowed roles, side effects, required fields.

9. **CancellationReason**
   - Active, sort order, notes-required flag, disallow reason.

10. **VisitOutcome**
    - Code/key, label, target status, further-work flag, unfinished flag, active, sort order.

11. **VisitReportOption**
    - Generic or specialized option table for reasons, hazards, confirmations, yes/no choices, labels/help text, and requirement rules.

12. **ReportContactMethod**
    - Channel key, validator, label, active, sort order, consent text, update routing.

13. **SupportedLanguage**
    - Code, locale, direction, native label, English label, active, default.

14. **LocalizedContent**
    - Scope/entity/key/locale/text/format/help text.

15. **SlaPolicy**
    - Priority/urgency/category/team scope, acknowledgement target, resolution target, working-day rules, timezone, active.

16. **DuplicatePolicy**
    - Radius, time window, category scope, location fallback, match confidence.

17. **FieldOperationsSettings**
    - Depot, map provider, geocoder, travel assumptions, on-site duration, photo rules, reverse-geocoding policy.

18. **NavigationEntry / ModuleSetting**
    - Module, route name, label, icon, permission, active, sort order.

19. **ErrorContent**
    - Machine code, status, locale, title, message.

## Cross-Cutting Code Changes Expected

Even after adding database models, future implementation should include:

- Caching and cache invalidation for singleton/theme/content/configuration reads.
- Safe defaults for configuration rows missing during migrations, startup, or first deploy.
- Import/export or data seeding for initial configuration.
- Admin validation for contradictory transitions, missing required semantics, and duplicate machine keys.
- Read-only machine keys for integration-critical codes unless a stable key migration mechanism is added.
- API payloads that serve active categories, subcategories, translations, priorities, urgencies, and SLA behavior from the database.
- One source of truth shared by server-side validation and browser behavior.
- Audit trail for configuration changes.
- Feature/lookup activation without deleting historical rows.
- Explicit fallback behavior when a configured value or translation is missing.

## Tests That Should Be Added During Implementation

An implementation pass will need to prove configurability rather than merely adding models. Suggested test coverage:

- Rename every lookup label and verify UI/API output uses the database label.
- Add new issue category, subcategory, priority, urgency, status, and outcome rows and verify domain behavior.
- Disable a category/status/contact method/language and verify it disappears from UI/API and cannot be selected.
- Change status semantic flags and verify dispatch, field work, approval, and dashboards respond to semantics rather than codes.
- Reconfigure status transitions and verify invalid and valid transitions.
- Change priority rank/SLA/colour and verify sorting, labels, and UI presentation.
- Change theme tokens and verify public, staff, mobile, chat, report, and admin surfaces.
- Change language/translation data and verify template, form, server, and JavaScript copy.
- Change depot/travel/duplicate rules and verify planning and duplicate matching.
- Change photo limits and validation thresholds consistently across browser and server.
- Verify missing/invalid configuration safely falls back without crashes or unsafe behavior.

## Items That Should Remain Environment-Only or Technical

To avoid misclassifying infrastructure, the following are not expected to belong in ordinary database configuration:

- Django `SECRET_KEY`
- database host/name/user/password and `DATABASE_URL`
- Cloudinary credentials and API secrets
- third-party API keys and tokens
- allowed-host/CSRF/cookie/security infrastructure
- middleware and installed app list
- Python package/static manifest configuration
- storage backend implementation
- root URL routing implementation
- test/development/production setting switches
- security middleware protections
- message storage backend

These values may still be exposed through database policy where appropriate, but credentials and deployment plumbing should remain environment-managed.
