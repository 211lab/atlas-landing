# Randomized visual facet catalogs

## Goal

Replace the generator's fixed wildstyle-on-brutalist-scene prompt with a reviewable, extensible composition of independently randomized visual facets. Make the selected choices discoverable from archived gallery images through linked chips and a generated catalog index.

## User-visible behavior

- Each generation randomly chooses one value from every visual facet catalog, including graffiti style, graffiti placement, camera/lens, composition, environment, paint/application treatment, lighting/effects, color palette, and other implemented visual contributors.
- Wildstyle and industrial/brutalist settings remain available as options, not mandatory defaults.
- Every catalog value has a stable ID, a concise display label, and a verbose, self-contained description used in the image prompt and displayed in the catalog index.
- Palette options include rainbow, red hues, blue hues, and a McDonald's red-and-yellow palette, alongside other useful palettes.
- The generated prompt combines the selected facet descriptions with shared invariants: the artwork spells exactly ATLAS, remains legible, appears physically integrated into the scene, respects requested weather, and avoids extraneous text/marks.
- The gallery card for a newly generated image displays a chip for each selected facet. Each chip links to the corresponding value in a generated catalog index (for example, `catalog.html#palette-rainbow`).
- The catalog index lists facet groups, values, labels, and their full detailed descriptions. It is generated from the same definitions used to form prompts and gallery chips.
- Archived image metadata includes the complete recipe as stable facet IDs and keeps the full prompt. Existing archives with the legacy `wildstyle` key and no facet recipe remain renderable without errors; retain useful legacy style display where possible.

## Non-goals

- No runtime user interface for choosing or weighting styles.
- No new API, model provider, dependency, or external catalog file format.
- No change to weather fetching, image generation/verifier protocol, acceptance gate, output paths, or non-fatal gallery archival behavior.
- No guarantee that an image model follows every prompt detail; this change randomizes and records prompt inputs, not model output.
- No changes to deployment configuration.

## Acceptance criteria

1. **Given** the catalog definitions, **when** a recipe is selected, **then** it contains exactly one catalog value for each supported facet and each value is selected from that facet's available options.
2. **Given** random selection, **when** tests inject or patch the random source, **then** all facets can be deterministically selected and each catalog is consulted once; the implementation remains straightforward to extend by adding catalog values.
3. **Given** the generated prompt, **when** a recipe is supplied, **then** every selected value's verbose description appears in the prompt, while shared spelling, legibility, weather, and no-extra-text requirements remain present and wildstyle/brutalist are not imposed unconditionally.
4. **Given** accepted generation, **when** metadata is written, **then** it records stable IDs for all selected facets and the assembled prompt.
5. **Given** a gallery image with new recipe metadata, **when** the gallery index is rendered, **then** its card shows escaped chips whose links resolve to catalog value anchors, and the generated catalog index contains those anchors and full descriptions.
6. **Given** legacy gallery sidecars with `wildstyle`, missing metadata, or otherwise absent new facet fields, **when** the gallery is rendered, **then** rendering succeeds and legacy images remain listed.
7. **Given** untrusted metadata fields, **when** chips and labels are rendered as HTML, **then** dynamic visible text and attributes are safely escaped.
8. **Given** the repository's test and CI workflow, **when** validation is run, **then** `python3 -m unittest discover -s tests`, `python3 -m py_compile generator/generate.py`, and `docker build -t atlas-background:test .` pass.

## Constraints and design

- Prefer immutable, explicit catalog entries and a recipe-selection boundary over parallel lists, scattered random choices, or conditionals in the prompt builder.
- Each option's prose must be sufficiently verbose and specific to guide image generation on its own; labels remain concise for chips.
- Facets are selected independently. Catalog prose should be written to combine broadly without contradictions; no hidden preference or weighting is introduced.
- Keep IDs URL-safe and stable because they appear in metadata, archive filenames where applicable, and catalog anchors. Do not rename legacy archive inputs unnecessarily.
- Retain HTML escaping, gallery escaping behavior, and metadata backward compatibility.

## Assumptions

- ASSUMPTION: A catalog entry can contain an explicit label and prompt description, and IDs are unique within a facet.
- ASSUMPTION: Independent selection across facets is the intended interpretation of “every individual facet” being randomly chosen; catalog descriptions will avoid incompatible requirements.
- ASSUMPTION: The static gallery catalog is generated into the runtime gallery data directory next to `index.html` and is linked from the gallery page.
- ASSUMPTION: The repository owner confirms that the branch history and contents are scrubbed and approved for public publication.

## Ordered implementation plan

1. Define immutable facet/catalog values and deterministic recipe selection in `generator/generate.py`; verify each catalog is non-empty, IDs are unique per facet, and verbose descriptions are available.
2. Refactor prompt assembly to accept the selected recipe and compose each verbose fragment with shared invariants; update `main()` to select once and use that same recipe for prompt and metadata.
3. Store the recipe IDs in new archive metadata and build HTML-escaped facet chips on gallery cards with links to stable catalog anchors. Preserve legacy metadata rendering.
4. Generate the static catalog index from the same catalog definitions, with a link from gallery index and full descriptions at the anchors.
5. Add unit tests covering choice, prompt composition, metadata/catalog anchors, escaping, and legacy entries; update README with randomization and gallery catalog behavior.
6. Run unit tests, compile check, Docker build, inspect the diff and repository status. Roll back by reverting the feature commit/branch; no migrations or changes to existing archived files are required.
7. Push the feature branch to `origin` and open a PR after the required checks pass.

## Open questions

- None blocking implementation.
