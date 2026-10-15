# GitHub Pages prompt generator

## Goal

Publish a dependency-free, static single-page prompt-generation tool on GitHub Pages. Let users inspect and include/exclude every randomized visual option and generate plain text prompts for copying into a vLLM interface. Keep the Python image-generation runtime separate while sharing one authoritative visual catalog.

## User-visible behavior

- A single responsive page lists every randomized visual facet and every catalog option currently used by the image prompt generator: placement, lens, composition, environment, paint/application, color palette, theme, and wildstyle prompt variation.
- The page identifies graffiti lettering as fixed wildstyle; no alternate graffiti style is offered. A separate wildstyle-prompt-variation pool may vary the treatment wording while every choice explicitly remains wildstyle. Lighting/effects is not randomized; the hourly backend derives it from live time and weather.
- Every option displays its concise label and full detailed prompt description. Each option has an accessible checkbox; options are included in the random pool when checked by default.
- Each generation independently chooses one enabled option per facet. A facet with no checked options is omitted from that prompt. If no option is enabled across all facets, generation reports that at least one must be enabled and does not produce an empty recipe prompt.
- The UI visibly reports the selected option in each included facet and puts only the assembled prompt text in a selectable, read-only text area. Prompt output includes fixed wildstyle prose, selected verbose descriptions, and shared requirements (ATLAS exact spelling, legibility, physical surface integration, photorealistic materials, no extraneous text); lighting is not randomized and the SPA does not claim to have live lookup data. Manual prompts defer to live time/weather context supplied by the caller. No HTML, code fences, recipe JSON, or generated image is included.
- The prompt panel appears immediately below the page introduction, before all visual options. The prompt text area and its generate/reroll and copy controls are grouped together at the top of the tool.
- All visual options appear below the prompt panel, grouped by facet in native collapsible sections that start closed. Each section summary identifies its facet and reflects its enabled-option count; expanding it reveals the individual option checkboxes and descriptions.
- Layout uses generous, consistent spacing and whitespace to distinguish the prompt, selected recipe, and options, while remaining usable on narrow screens.
- Users can generate/reroll, copy the prompt, and reset all options to enabled. Copy reports success or a useful fallback/error status. No provider/API call is made.
- The page works as a static GitHub Pages project site under a repository subpath; all assets and catalog data load locally from the published artifact.
- GitHub Actions publishes the page from `main` using the Pages artifact/deploy flow. The existing generator container/Gitea deployment behavior remains intact.
- README links to the published tool and explains that it creates copyable prompt text locally without contacting a vLLM or image API.

## Non-goals

- No calls to vLLM, OpenRouter, image-generation APIs, or any backend service.
- No prompt history, authentication, server-side state, share links, weighting system, or arbitrary catalog editor.
- No generated images or runtime gallery data in the Pages artifact.
- No changes to the deployed weather generator's generation cadence or verification/publishing behavior.

## Acceptance criteria

1. **Given** the shared catalog source, **when** the page loads, **then** every supported facet and catalog option appears with its label, verbose description, and an enabled checkbox.
2. **Given** a user disables options, **when** they generate, **then** exactly one enabled option is randomly selected for each facet with enabled options; disabled options are never selected, and empty facets are omitted.
3. **Given** deterministic random values in tests, **when** prompt generation runs, **then** selected descriptions occur in the prompt and shared ATLAS spelling/legibility/no-extra-text requirements remain present.
4. **Given** every option is disabled, **when** generation is requested, **then** the app explains that at least one option must be enabled and does not replace the existing output with an unusable prompt.
5. **Given** a generated prompt, **when** the user copies it, **then** the clipboard receives only the exact plain-text prompt; feedback is visible and an unsupported clipboard API has a usable manual-copy fallback.
6. **Given** the public site is served below a path prefix, **when** the page and catalog load, **then** all local paths resolve without a root-domain assumption and the app works without a server/API.
7. **Given** GitHub Actions builds the Pages artifact, **when** it is inspected, **then** it contains only the SPA assets and shared catalog JSON, and the deployment job has least-privilege Pages permissions.
8. **Given** existing backend tests and container build, **when** validation runs, **then** they continue to pass and the GitHub Pages JavaScript/catalog tests pass.
9. **Given** a visitor reading the README, **when** they want to use the prompt tool, **then** the published project Pages URL and text-only/no-backend behavior are clear.
10. **Given** the tool page loads, **when** the user scans it, **then** prompt output and generate/copy controls come before the visual options.
11. **Given** the visual options, **when** the page loads, **then** every facet is represented by a closed native disclosure section with a label and enabled count; opening it exposes all options in that facet.
12. **Given** options are toggled, **when** the enabled pool changes, **then** the corresponding section count updates, while reset enables every option and refreshes all counts.
13. **Given** the options and generated prompt, **when** the user inspects them, **then** graffiti lettering is fixed wildstyle with no alternate style choices, wildstyle prompt variations are clearly labeled as variations that preserve the same style, and lighting/effects has no random option.

## Constraints and design

- Make `generator/catalogs.json` the single source of truth for fixed prompt requirements and randomized facet IDs, labels, option IDs/labels, and detailed descriptions. Load this data in Python for the deployed generator and in the browser SPA; do not maintain a copied second catalog.
- Keep the app static and dependency-free. Use semantic HTML, native controls, responsive CSS, and browser ES modules.
- Inject the random source into the pure prompt-recipe function for deterministic unit tests.
- Use DOM `textContent` for catalog-provided content; do not interpolate descriptions into HTML.
- The Pages workflow should trigger only for relevant `main` changes and manual dispatch, assemble a clean artifact, use official Pages actions, and not receive repository secrets.
- Retain the current public site privacy, secret, and generated-data rules; publish no runtime output.

## Assumptions

- ASSUMPTION: "All criteria that is random" refers to the eight randomized visual facet catalogs used by `select_recipe()`, including wildstyle prompt-variation and theme pools; fixed wildstyle lettering, live lookup-derived lighting/weather, image-model selection, and environment/configuration secrets are not random prompt facets.
- ASSUMPTION: Every option starts enabled. Disabling all options in one facet omits that facet; disabling all options globally is an input error.
- ASSUMPTION: The GitHub Pages URL is the standard project site for `211lab/atlas-landing`; the deployment artifact is rooted at the repository site path.
- ASSUMPTION: GitHub repository Pages settings allow the `github-pages` environment and GitHub Actions deployment. If repository settings prevent deploy, leave the workflow ready and report the required owner-side setting rather than changing repository security policy.

## Ordered implementation plan

1. Create a focused branch from current `origin/main`; extract the existing eight `CATALOGS` into `generator/catalogs.json` and load the same data from Python. Verify generator tests and catalog parity.
2. Build a standalone `prompt-tool/` SPA with accessible facet/option checkboxes, enabled-pool recipe selection, selected-option summary, text-only prompt output, copy feedback/fallback, reroll, and reset.
3. Add pure JavaScript selection/prompt functions and Node built-in tests for deterministic pools, omitted facets, all-disabled input, and shared requirements.
4. Add a least-privilege GitHub Pages Actions workflow that packages only SPA files plus catalog JSON. Extend validation to run the Node tests; document the published tool in README; keep existing Python/Docker/Gitea workflows behavior intact.
5. Run Python tests, compile check, Node tests, Docker build, inspect artifact contents and workflow permissions, and run the secret scan.
6. Commit, push, and open a PR from the focused branch. After merge, confirm Pages deployment and report its URL. Roll back by reverting the Pages workflow/site commit; generator catalog data remains backwards compatible in JSON form.
7. For the layout refinement, put the prompt panel first, move options below it, render options as native closed disclosure sections with live enabled counts, and tune spacing/mobile behavior in `prompt-tool/index.html`, `prompt-tool/app.js`, and `prompt-tool/styles.css`. Add focused UI-structure/count tests and publish through the existing Pages workflow.

## Open questions

- None blocking. Pages deployment depends on the repository-level GitHub Pages source/environment configuration noted in Assumptions.
