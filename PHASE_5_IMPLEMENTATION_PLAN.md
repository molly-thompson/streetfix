# Phase 5 Implementation Plan: Database Theme and Semantic UI

## Goal

Make all StreetFix UI presentation database-configurable and replace UIkit with
a compact, project-owned component system.

The system will:

1. persist Tier 1 and selected Tier 2 values in `ThemeSettings`;
2. resolve missing Tier 2 values and all Tier 3 values on the server;
3. render one complete resolved CSS-variable document into the page;
4. style a deliberately small set of semantic component classes from those
   variables;
5. use native HTML for interaction where possible and narrowly scoped,
   tested JavaScript only where native behavior is insufficient.

No dynamic, in-session theme switching is required.

## Visual Reference

Use <https://streetfix-brand-guidelines.vercel.app> as the visual reference for
the component system.

Baseline:

- primary teal: `#0f6b63`;
- hover teal: `#0d5e57`;
- active/focus teal: `#0b524c`;
- canvas: `#f5f6f8`;
- surface: `#ffffff`;
- body text: `#374151`;
- emphasis text: `#111827`;
- muted text: `#667085`;
- borders: `#e7e9ee`;
- success: `#2f6b3c` on `#eaf3ec`;
- warning: `#8a6100` on `#fff8e0`;
- danger: `#a93226` on `#fbf0ee`;
- info: `#335c9a` on `#eef3fa`.

These are initial persisted defaults, not hard-coded component colors.
Administrators may configure alternatives through the resolved theme system.

Typography:

- IBM Plex Sans for application copy;
- IBM Plex Mono only for report IDs and precision details;
- public body copy: 16px;
- staff body copy: 14px;
- supporting copy and captions: never smaller than 12px;
- body line height: 1.5.

IBM Plex Sans and IBM Plex Mono are self-hosted design assets with fixed family
names. They are not database fields or administrator uploads: configuring font
files requires licensing, `@font-face`, weight, fallback, and performance
knowledge that is inappropriate for the normal settings interface. The
database controls type size, staff/public scale, weight, and density.

Visual principles:

- public screens are open, calm, and single-task;
- office screens are compact and scannable;
- field screens are glanceable, direct, and generous in touch target size;
- status always combines text or an icon with color;
- use sentence case;
- keep the map-pin/route visual language flat, geometric, and high contrast;
- avoid decorative gradients, heavy shadows, and ornamental icon treatments;
- use audience-specific density rather than one global density.

## Architectural Decision

StreetFix will not migrate to Bootstrap and will not adopt a broad browser
theming runtime.

Reasoning:

- the existing UI already contains extensive custom chat, staff, and mobile
  field-work layouts;
- a complete framework would introduce a second visual system that must be
  overridden;
- StreetFix needs a small, stable set of design tokens and application
  components rather than Bootstrap's complete component catalogue;
- native HTML covers most of the application and has better default
  accessibility than framework-like custom controls;
- complex keyboard/ARIA behavior can be introduced selectively without
  carrying the defaults and retinting burden of a full framework.

## Accessibility Strategy

The component system must use native semantics and tested behavior rather than
recreate inaccessible controls.

Prefer:

- `<a>` for navigation and destinations;
- `<button>` for actions;
- `<label>`, `<input>`, `<select>`, and `<textarea>` for forms;
- `<fieldset>` and `<legend>` for groups;
- semantic `<table>`, `<thead>`, `<tbody>`, `<th>`, and `<td>`;
- `<nav>`, `<main>`, `<header>`, `<footer>`, `<section>`, and `<aside>`;
- `<details>` and `<summary>` for simple disclosure;
- native `<dialog>` for dialogs when supported, with a tested fallback;
- native `<progress>` where suitable;
- `role="alert"` or a live region for notifications.

Do not create project-owned custom implementations for complex widgets unless a
visible StreetFix requirement cannot be met natively. Tabs, menus, comboboxes,
modals, accordions, and other ARIA state machines require an accessibility
review before implementation. If the interaction becomes complex, use a small
headless behavior package rather than adding another broad visual framework.

## Boundaries

### Database-configurable

- branding and favicon;
- configurable brand image/wordmark pairing;
- colour roles and semantic colour roles;
- radii, borders, outlines, shadows, opacity, and motion;
- typography inputs;
- spacing/density inputs;
- used component presentation tokens;
- priority/status styling;
- map route, marker, and depot styling;
- focus, disabled, hover, active, and selected states;
- intentional component-level overrides.

### Backend-derived, never persisted

- RGB companions when needed;
- mixed surfaces and subtle colours;
- hover and active states;
- contrast-derived foreground colours;
- shadow/elevation outputs;
- generated icon/data URLs;
- reusable component tokens;
- exact CSS custom-property aliases;
- calculated typography, radius, spacing, or opacity relationships.

### Environment/Django infrastructure

- static-file backend;
- secrets and media provider credentials;
- CSP/security policy;
- deployment cache backend;
- URL routes and middleware.

## End-State Acceptance Criteria

Phase 5 is complete when:

- UIkit CSS, JavaScript, attributes, and classes are absent from active
  templates, JavaScript, tests, and source styles.
- No replacement framework is introduced.
- Every Tier 1 and editable Tier 2 value is persisted in `ThemeSettings`.
- Every Tier 3 value is resolved by a service and is not editable or stored.
- Every page receives one complete, request-independent resolved theme
  document.
- All application UI uses semantic component classes and native HTML.
- Priority, status, and map presentation comes from database configuration or
  the resolved theme.
- Public, staff, mobile, authentication, intake, triage, analytics, and error
  surfaces render against changed theme values without source edits.
- Missing optional values are derived rather than emitted as empty CSS
  declarations or conflicting static fallbacks.
- All configured and derived foreground/background pairs pass contrast
  validation or save is rejected with field-specific errors.
- Component keyboard behavior, focus visibility, focus order, labels,
  announcements, and responsive behavior pass automated and manual checks.
- Tests prevent presentation literals from being introduced outside an
  explicit, narrow allowlist.

## Current Surface Inventory

The migration covers:

- shared base, navigation, messages, footer, and page shell;
- allauth layouts, forms, buttons, fields, tables, panels, and alerts;
- public report chat and its chips/typing/error states;
- public report submission form and success page;
- analytics overview and error pages;
- manager shell, dashboard, dispatch list/detail, and tables;
- triage shell and dashboard;
- officer mobile navigation, jobs, alerts, maps, arrival, and visit reports;
- Django message variants and custom status/priority chips;
- Leaflet markers, route styling, and map controls;
- favicon and brand image presentation.

## Proposed Component Catalogue

Keep the catalogue small and add a component only for a repeated, visible need.

### Foundation

- `sf-page`;
- `sf-container`;
- `sf-stack`;
- `sf-cluster`;
- `sf-grid`;
- `sf-section`;
- `sf-divider`;
- visually hidden utility.

### Navigation and structure

- `sf-site-header`;
- `sf-brand`;
- `sf-nav`;
- `sf-nav-list`;
- `sf-mobile-nav`;
- `sf-sidebar`;
- `sf-page-header`;
- `sf-footer`.

### Controls

- `sf-button` with semantic variants;
- `sf-button-group`;
- `sf-link`;
- `sf-icon-button`;
- `sf-form`;
- `sf-field`;
- `sf-label`;
- `sf-input`, `sf-select`, `sf-textarea`;
- `sf-help`;
- `sf-error`;
- `sf-checkbox` and `sf-radio`.

### Content

- `sf-card`;
- `sf-card-header/body/footer`;
- `sf-panel`;
- `sf-alert`;
- `sf-badge`;
- `sf-status`;
- `sf-priority`;
- `sf-table`;
- `sf-list`;
- `sf-empty-state`;
- `sf-progress`.

### Officer/mobile

- `sf-app-shell`;
- `sf-tabs`;
- `sf-job-card`;
- `sf-action-bar`;
- `sf-step`;
- `sf-callout`;
- `sf-photo`;
- `sf-safety`.

Components must be named by role rather than appearance.

## Theme Contract

### Tier 1 inputs

Required colour inputs:

- `primary_color`;
- `background_color`;
- `text_color`.

Category-specific Tier 1 values:

- borders/outlines: `border_width`, `border_style`, `outline_width`,
  `outline_offset`;
- radii: `radius_sm`, `radius`, `radius_lg`, `radius_xl`;
- typography: fixed self-hosted IBM Plex Sans/Mono families, plus configurable
  `font_size_base`, `font_size_staff`, and `font_weight_base`;
- motion: `duration_fast`, `duration_base`, `duration_slow`,
  `ease_standard`, `ease_out`;
- elevation/opacity: `shadow_base`, `focus_ring_alpha`,
  `disabled_opacity`;
- spacing/density: `space_unit`, `density_scale`, if custom CSS requires them.

### Selected Tier 2 inputs

Neutral:

- `surface_color`;
- `surface_elevated_color`;
- `emphasis_text_color`;
- `muted_text_color`;
- `disabled_text_color`;
- `border_color`;
- `link_color`;
- `link_hover_color`;

Primary:

- `on_primary_color`;
- `primary_hover_color`;
- `primary_active_color`;
- `primary_text_color`;
- `primary_surface_color`.

Semantic families:

- `secondary_color`;
- `success_color`;
- `info_color`;
- `warning_color`;
- `danger_color`;
- optional corresponding `*_text_color`, `*_surface_color`,
  `*_hover_color`, `*_active_color`, and `on_*_color`.

Component tokens should be added only when a meaningful override is needed:

- navbar background/foreground;
- brand/icon foreground;
- card, dialog, and popover/elevated surfaces;
- form control, placeholder, disabled, and focus states;
- backdrop/overlay;
- tooltip;
- selected/active navigation;
- map route, marker, depot marker, and fallback marker.

Tier 2 must not become an unrestricted arbitrary-CSS-variable field.

### Tier 3 outputs

The resolver must produce:

- all required RGB companions;
- neutral and elevated surfaces;
- solid hover/active colours;
- semantic solid, text, surface, and on-solid roles;
- contrast-safe foregrounds;
- focus ring and shadow values;
- body/emphasis/muted/disabled pairs;
- typography scale and line-height tokens;
- radius/spacing tokens;
- component-ready CSS variables;
- priority/status/map variables;
- generated icon/data-URL colours where the UI uses them;
- deterministic JSON and CSS-variable mappings.

Tier 3 values are never fields on `ThemeSettings`.

## Phase 5A: Theme Model and Backend Resolver

### 5A.1 Extend `ThemeSettings`

- Add selected Tier 1 and Tier 2 fields listed above.
- Preserve and backfill all existing values.
- Add validators for CSS lengths, color values, shadows, opacity, durations,
  font stacks, and spacing.
- Remove `navbar_brand_icon` as a selectable icon.
- Add an optional `brand_image` upload suitable for PNG or SVG. It sits beside
  `site_name`; do not assume a configured image always contains a full lockup.
- Keep favicon independently configurable.
- Validate brand image dimensions, format, and accessible fallback behavior.
- Add a revision number or saved timestamp for cache keys.

### 5A.2 Build a pure resolution service

Create a service or value object that:

- converts stored values to a complete resolved theme;
- derives missing Tier 2 values;
- derives every Tier 3 value;
- creates an explicit CSS-variable document;
- produces structured contrast results for tests and previews;
- has no request or template dependency.

Suggested API:

```python
ResolvedTheme.resolve(settings) -> ResolvedTheme
ResolvedTheme.css_variables
ResolvedTheme.contrast_results
```

Keep colour mixing, validation, and component-token derivation out of models,
templates, and JavaScript.

### 5A.3 Define derivation behavior

- Mix colours in sRGB.
- Derive subtle semantic surfaces from solid semantic colours and the page
  surface.
- Derive semantic text for those surfaces.
- Derive hover/active values consistently.
- Select black or white/on-solid alternatives by contrast when omitted.
- Emit concrete values; do not rely on browser `color-mix()` for core output.
- Treat blank Tier 2 values as “derive,” never as an empty declaration.
- Provide a complete fallback document when the singleton is absent.

### 5A.4 Validate contrast

Validate actual foreground/background pairs:

- body/page;
- body/surface and elevated surface;
- muted, emphasis, disabled, and tertiary text on each used surface;
- links and hovered links on page/surfaces;
- text on primary and semantic solid backgrounds;
- semantic text on semantic subtle surfaces;
- hovered/active button states;
- alerts, badges, navbar, tooltip, and map labels;
- priority and status chips on their configured backgrounds.

Attach errors:

- to the explicit Tier 2 field that caused the failure;
- otherwise to the Tier 1 source used to derive the invalid value.

### 5A.5 Cache and expose the resolved document

- Cache with the theme revision.
- Invalidate on save/delete.
- Update the context processor to expose resolved CSS variables, branding,
  favicon, brand image, and revision.
- Render variables on the page root/theme scope.
- Keep the resolved output deterministic and request-independent.

### Acceptance tests

- Minimal three-colour theme resolution.
- Complete override theme resolution.
- Dark/high-contrast themes.
- Every expected component variable is present and non-empty.
- Explicit Tier 2 values survive resolution.
- Blank Tier 2 values derive expected output.
- Contrast failures identify the correct field.
- Cache invalidation occurs after theme edits.
- Missing singleton uses safe resolved fallback values.

## Phase 5B: Component Foundation

### 5B.0 Icon system

Use a single dependency-free SVG symbol sprite for application icons.

- Pick one coherent, permissively licensed icon family and vendor only the
  symbols StreetFix uses.
- Store the selected paths in `static/icons/streetfix-icons.svg` as SVG
  `<symbol>` definitions.
- Render icons through one Django template tag or shared include:

  ```html
  <svg class="sf-icon" aria-hidden="true" focusable="false">
    <use href="/static/icons/streetfix-icons.svg#arrow-right"></use>
  </svg>
  ```

- Icons inherit `currentColor`; do not set fill/stroke colors in individual
  symbols.
- Use consistent view boxes, stroke widths, sizing, and alignment.
- Decorative icons are hidden from assistive technology and paired with visible
  text.
- Meaningful icon-only controls receive an accessible name through text or
  `aria-label`.
- Never rely on color or an icon alone to communicate status.
- Maintain a documented symbol allowlist and test that every referenced symbol
  exists.
- Preserve the selected icon family's license and attribution in the
  repository.
- Do not add application icons to database configuration. They are design-system
  assets; the configurable brand image is the branding concern.

This is preferable to duplicating inline SVG paths because it provides one
source for each icon, one consistent visual language, caching, no JavaScript
dependency, no per-icon requests, and an easy future replacement path.

Do not use an external icon font. It adds loading and rendering fragility
without improving accessibility or performance for the small set StreetFix
needs.

### 5B.1 Establish CSS architecture

Suggested files:

- `static/css/theme.css`: resolved token aliases and global semantic defaults;
- `static/css/components.css`: reusable StreetFix component classes;
- `static/css/layout.css`: page, grid, stack, and responsive layout;
- `static/icons/streetfix-icons.svg`: approved application icon symbols;
- application files for genuinely app-specific structure.

Rules:

- no framework-specific utility classes;
- no hard-coded application colors in component files;
- state rules must consume resolved variables;
- layout CSS must not redefine semantic colors;
- responsive breakpoints are either theme tokens or documented structural
  constants;
- use cascade layers if they improve predictability without adding complexity.

### 5B.2 Build components from native HTML

Start with:

- buttons/links/icon buttons;
- forms and validation;
- cards/panels;
- alerts/live regions;
- badges/status/priority;
- tables;
- page headers/navigation;
- disclosure;
- empty states/progress.

Every component must define:

- normal state;
- hover/focus state where applicable;
- active/pressed state;
- disabled state;
- responsive behavior;
- forced-colors/high-contrast behavior;
- reduced-motion behavior.

### 5B.3 Component behavior

Implement only:

- responsive navigation toggle;
- dismissible alerts if retained;
- native or minimal dialog focus management;
- simple tab-like behavior if a workflow genuinely requires it.

Keyboard checks include:

- all controls are reachable in logical order;
- focus is always visible;
- Escape closes transient UI where expected;
- dialog focus is contained and restored;
- expanded/pressed/selected state remains synchronized;
- status updates use an appropriate live region.

### 5B.4 Domain token integration

- Connect priority chips to database priority color/style.
- Connect status chips to database status color/style.
- Add map route, marker, depot, fallback-marker, and map-control tokens.
- Remove Python and JavaScript presentation dictionaries.
- Keep semantic meaning outside CSS: labels and codes remain domain data.

## Phase 5C: Shared Shell and Authentication

Migrate:

- `templates/base.html`;
- errors;
- allauth layouts/elements;
- account and custom registration/login pages.

Replace:

- UIkit grid/flex/container classes;
- navbar attributes and JavaScript;
- alert/close behavior;
- UIkit icon attributes;
- framework form/button/panel classes.

Preserve:

- route names and destinations;
- branding;
- responsive navigation;
- message tags and roles;
- authentication behavior and validation;
- keyboard order and focus behavior.

Acceptance:

- all existing shared/authentication tests pass;
- no UIkit symbols remain in shared templates;
- navigation works with keyboard and a phone-sized viewport;
- shared UI responds to every resolved theme token.

## Phase 5D: Public Intake

Migrate:

- report chat;
- report submission form;
- submission success page.

Replace:

- UIkit card/grid/form/button/alert/label classes;
- UIkit accordion behavior;
- icon-button markup;
- JavaScript selectors coupled to UIkit.

Retint:

- chat bubbles and typing;
- progress;
- chips;
- photo controls;
- validation/live-region messages;
- priority/SLA/state badges;
- success and failure states.

Acceptance:

- chat and form workflows pass existing tests and browser tests;
- component behavior works with keyboard only;
- desktop and mobile layouts remain usable;
- theme values change chat, controls, alerts, and status presentation.

## Phase 5E: Manager, Triage, Analytics, and Errors

Migrate:

- manager shell/dashboard;
- dispatch list/detail/table;
- triage shell/dashboard;
- analytics overview;
- remaining error surfaces.

Preserve:

- links/routes;
- dashboard semantics;
- form actions;
- status/priority meaning;
- table accessibility;
- context keys.

Retint:

- navigation/sidebar;
- metrics and progress;
- tables and rows;
- cards/panels;
- callouts;
- status/priority;
- analytics components.

Acceptance:

- existing staff, triage, dispatch, and analytics tests pass;
- wide tables have a tested responsive strategy;
- keyboard users can navigate and trigger every action;
- configured priority/status labels and colors display consistently.

## Phase 5F: Officer Mobile and Maps

Migrate:

- officer base;
- job list/current job;
- arrival/photo workflow;
- report and alerts;
- navigation/steps/action bars;
- Leaflet map and route UI.

Retint:

- app chrome;
- action bar;
- job cards/rows;
- current-step/status states;
- upload/photo states;
- danger/safety callouts;
- map controls, markers, and routes;
- disabled actions.

Maintain a mobile-first layout rather than forcing the shared desktop component
geometry into field screens.

Acceptance:

- existing officer/field-work tests pass;
- phone-sized browser tests cover primary workflows;
- touch targets and focus states are adequate;
- map marker and route colors update from the database/theme;
- no UIkit behavior remains in officer JavaScript/templates.

## Phase 5G: Admin Preview

Add a preview contained within theme admin:

- primary, secondary, semantic, outline, and disabled buttons;
- form controls and validation states;
- cards, alerts, badges, statuses, priorities, and tables;
- navigation and progress;
- light and elevated surfaces;
- representative mobile controls;
- contrast summary for current and derived pairs.

The preview must consume `ResolvedTheme.css_variables`; it must not duplicate
resolver logic or color calculations.

## Phase 5H: Cleanup

Only after all active surfaces are migrated:

- delete `static/uikit/`;
- remove UIkit scripts/styles from base templates;
- remove active `uk-*`, `uk-...`, and UIkit JavaScript selectors;
- delete obsolete UIkit test assertions;
- reduce the following to layout/app-specific rules:
  - `fieldops.css`;
  - `fieldops-mobile.css`;
  - `fieldops-mobile-extras.css`;
  - `report-chat.css`;
  - `report-submission-form.css`;
  - `theme.css`.
- replace hard-coded presentation values with approved component/theme tokens;
- document component markup, states, accessibility requirements, and the
  approved icon symbols.

## Accessibility QA

Automated checks:

- label/control association;
- duplicate IDs;
- valid ARIA references;
- button/link semantics;
- focusable elements in modals/navigation;
- missing alternative text;
- colour contrast in tested states;
- keyboard interactions with custom behavior.

Manual checks:

- keyboard-only public report flow;
- keyboard-only manager/triage flow;
- keyboard-only officer action flow;
- screen-reader landmarks/headings/labels;
- focus visibility and restoration;
- reduced-motion setting;
- zoom at 200% and 400%;
- narrow viewport/reflow;
- high-contrast/forced-colors mode.

If a custom interaction cannot pass these checks, replace it with native HTML
or a narrowly scoped audited headless behavior dependency.

## Test Strategy

### Backend/theme tests

- resolver determinism and completeness;
- model validation and contrast errors;
- migration/backfill behavior;
- cache invalidation and fallback;
- status/priority/map token exposure.

### Template/component tests

- shared component markup;
- no UIkit tokens/classes/attributes;
- routes and context remain unchanged;
- message, validation, alert, badge, and status semantics;
- no presentation literals outside allowlist.

### Browser tests

- public report flow;
- account/auth flow;
- manager/dispatch/triage flow;
- officer mobile flow;
- responsive navigation;
- dialogs/disclosure;
- focus management;
- Leaflet map rendering;
- representative theme changes.

## Suggested Commit Breakdown

1. `feat(theme): add theme inputs and backend resolver`
2. `test(theme): cover derivation contrast caching and fallbacks`
3. `feat(ui): add semantic component foundation`
4. `refactor(ui): migrate shared shell and authentication from UIkit`
5. `refactor(intake): migrate public reporting UI from UIkit`
6. `refactor(ui): migrate manager triage and analytics UI from UIkit`
7. `refactor(fieldops): migrate officer mobile UI and maps from UIkit`
8. `feat(theme): add theme admin preview`
9. `refactor(ui): remove UIkit and presentation literals`
10. `test(ui): add accessibility responsive and theme coverage`

Regroup commits where dependencies require it, but each commit should leave
the application runnable and migrate a coherent surface.

## Quality Gates

Before each commit:

```shell
uv run ruff check --fix
uv run ruff format
```

If templates are modified:

```shell
uv run djlint . --reformat
uv run djlint . --lint
```

At the end of each migration subsection and before Phase 5 completion:

```shell
uv run python manage.py makemigrations --check --dry-run
uv run mypy .
uv run python manage.py collectstatic --noinput
uv run pytest
```

Run browser/accessibility checks for every migrated surface.

## Risks and Mitigations

- **Risk:** Accessibility regressions from custom interaction.
  - **Mitigation:** use native elements first and test custom behavior heavily.
- **Risk:** Component catalogue expands into a framework.
  - **Mitigation:** require repeated visible usage before adding a component.
- **Risk:** Different pages create competing class/state definitions.
  - **Mitigation:** one component stylesheet and documented state contract.
- **Risk:** UIkit-specific behavior is overlooked.
  - **Mitigation:** inventory scripts, attributes, selectors, and tests before
    deleting each surface.
- **Risk:** Theme resolver output and CSS consume values differently.
  - **Mitigation:** concrete named component variables plus rendered browser
    tests.
- **Risk:** Mobile officer UX becomes desktop-oriented.
  - **Mitigation:** keep mobile layouts custom and shared components narrowly
    scoped.
- **Risk:** Status/priority presentation drifts from database data.
  - **Mitigation:** one resolved domain-token path for Python, templates, and
    JavaScript.
- **Risk:** Icon migration breaks controls or branding.
  - **Mitigation:** use one approved SVG sprite, assert referenced symbol
    availability, and keep the configurable brand image separate from fixed
    application icons.

## Follow-Up Items

After Phase 5:

- make navigation and content copy database-configurable;
- support database languages/translations;
- expand the component catalogue only when a second visible use case exists;
- evaluate a headless accessibility package only if a genuinely complex
  widget is introduced;
- remove remaining obsolete settings-derived presentation constants.

