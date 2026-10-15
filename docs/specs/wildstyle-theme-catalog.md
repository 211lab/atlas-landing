# Fixed wildstyle and randomized themes

## Goal

Keep graffiti lettering wildstyle in every generated image prompt, while adding a separate randomized theme facet for techno-centric and speculative visual directions. Expose the new theme pool in the Pages prompt generator and update the Atlas Docker generator with equivalent behavior.

## User-visible behavior

- Wildstyle lettering is a fixed prompt requirement, not a random catalog value and not a selectable SPA option. It is always included in backend and SPA-generated prompts.
- A separate `wildstyle-variation` facet provides several detailed prompt formulations/treatments for wildstyle. Each generation picks one enabled variation when the pool is nonempty. Every variation explicitly preserves wildstyle lettering and legibility; these are prompt variations, not alternate graffiti styles.
- The randomized catalog no longer contains a graffiti-style facet. A new `theme` facet offers detailed choices including solarpunk, steampunk, cyberpunk, and other technology-oriented/speculative themes, including post-apocalyptic salvage and post-war reconstruction directions.
- Lighting/effects is not a randomized facet. In the hourly backend generator, actual local weather and time-of-day lookup remain authoritative inputs to `weather_elements()` and `lighting()` and are included directly in the prompt.
- The manual SPA does not perform live weather lookups; it must not present random lighting as live conditions. Its prompt directs the caller to supply and follow live time/weather details rather than inventing them.
- Random theme and environment descriptions may establish technology, materials, and architecture, but must not assume a time of day, weather, wet surfaces, or a lighting effect that conflicts with the live lookup.
- Theme and wildstyle-variation options appear in the SPA's existing option controls and can be enabled/disabled like other randomized facets. Disabling every variation does not disable the fixed wildstyle standard.
- Backend metadata records `wildstyle` as the fixed value and stores randomized selections only under `facets`.
- Legacy gallery records and old `wildstyle` metadata continue to render.
- Publish the SPA/catalog change to GitHub Pages and publish equivalent Docker generator behavior through the Atlas Gitea main/tag release pipeline.

## Non-goals

- No selectable graffiti lettering styles or non-wildstyle variants.
- No changes to the image-generation/verifier API, weather behavior, gallery lifecycle, or Pages interaction model.
- No force-push, remote history rewrite, or publishing the Atlas branch history to GitHub.
- No push to a second image registry. GitHub Pages publication and the Atlas internal image build are separate destinations.

## Acceptance criteria

1. **Given** catalog data, **when** randomized facets are loaded, **then** there is no random graffiti-style or lighting/effects facet, and randomized `theme` and `wildstyle-variation` facets exist with verbose options.
2. **Given** any backend generation, **when** a recipe and prompt are built, **then** fixed wildstyle description and one enabled wildstyle variation are included when that pool is nonempty, `style` and `lighting` keys are not randomly selected, local weather/time-derived lighting remains authoritative, and other random facets are selected once.
3. **Given** accepted-image metadata, **when** it is written, **then** `wildstyle` is the stable fixed ID `wildstyle`, and `facets` contains only selected randomized facets including theme and wildstyle variation when selected.
4. **Given** the SPA loads, **when** the option facets render, **then** wildstyle is clearly described as fixed/non-random and has no graffiti-style checkbox, lighting/effects has no random checkbox, and all theme and wildstyle-variation choices are individually visible and toggleable.
5. **Given** an SPA prompt is generated with any enabled pools, **when** the prompt is assembled, **then** fixed wildstyle prose and one enabled wildstyle variation are included when that pool is nonempty, random lighting instructions are absent, live time/weather details are deferred to the caller, and the selected theme is included when enabled; disabled options are never chosen.
5a. **Given** a random theme/environment description is selected, **when** it appears beside live weather/time prompt context, **then** it does not require incompatible night/day, precipitation, wetness, or lighting effects.
6. **Given** legacy gallery sidecars, **when** the gallery is rendered after the catalog change, **then** old style captions/records still render and new records show fixed wildstyle without catalog lookup failures.
7. **Given** the GitHub branch is merged, **when** Pages deploys, **then** the live SPA serves the new theme options and fixed wildstyle behavior.
8. **Given** the Atlas backend change is merged and tagged, **when** the release workflow runs, **then** it builds/pushes the tagged Docker image, promotes the GitOps values tag, and Argo CD syncs the new image.
9. **Given** Python, Node, Docker, and secret-scan gates, **when** validation runs, **then** all pass on the GitHub source and the Atlas backend equivalent passes its Python/container checks.

## Constraints and design

- Keep the JSON catalog as the GitHub/Python shared source. Store fixed wildstyle data at `fixed.wildstyle` (`id`, `label`, `description`) and selectable random pools, including `wildstyle-variation`, in `facets`. Variation options must never describe a non-wildstyle alternative.
- Python `select_recipe()` and browser recipe selection consume only `facets`; the fixed section is added to prompt assembly independently and never enters a random pool.
- Use stable IDs and verbose self-contained theme descriptions. Preserve metadata and gallery compatibility as much as possible.
- The Atlas remote is behind the GitHub Pages branch and has an older inline catalog implementation. Transfer only the equivalent generator change to an Atlas-based branch; do not attempt a force update or push GitHub-only Pages files into Atlas history.
- **ASSUMPTION:** `v0.19.0` is the latest Atlas release tag; release this change as `v0.20.0` unless that tag already exists.
- **ASSUMPTION:** The user requests publication to both remotes: GitHub (Pages) and Atlas (Docker/GitOps), not two image registries.
- **ASSUMPTION:** “Multiple versions of the prompt” means one randomly chosen, visible/toggleable wildstyle prompt-treatment variant per generation; all variants retain wildstyle as the only graffiti style.

## Ordered implementation plan

1. On a branch based on current GitHub `origin/main`, change `generator/catalogs.json` to separate fixed wildstyle prose from randomized facets; remove random style and lighting facets, and add detailed theme and wildstyle-variation facets.
2. Update Python loading, prompt assembly, recipe selection, metadata, gallery behavior as needed, and unit tests. Update the SPA to show fixed wildstyle as non-selectable and use the new theme pool.
3. Run Python/Node/compile/Docker/gitleaks checks; commit, push to GitHub, merge after CI, and verify Pages deployment.
4. On a separate branch based on fresh `atlas/main`, port the equivalent backend catalog/prompt/metadata behavior using Atlas's current inline implementation. Run Python/Docker checks, merge to Atlas `main`, create/push the next release tag, and verify build, GitOps promotion, and Argo health.
5. Keep the publication histories separate and fast-forward safe; rollback by reverting the GitHub and Atlas feature commits and, if necessary, promoting the prior image tag through GitOps.

## Open questions

- None blocking. Confirm the proposed release version against remote tags before creating it.
