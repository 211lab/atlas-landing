import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { enabledCount, generatePrompt, selectRecipe, SHARED_REQUIREMENTS, LIVE_CONTEXT_DIRECTIVE } from "../prompt-tool/prompt.mjs";

const catalogs = {
  fixed: { wildstyle: { id: "wildstyle", label: "Wildstyle", description: "Fixed wildstyle description" } },
  facets: [
    { id: "first", label: "First facet", entries: [{ id: "a", label: "A", description: "Description A" }, { id: "b", label: "B", description: "Description B" }] },
    { id: "empty", label: "Empty facet", entries: [{ id: "c", label: "C", description: "Description C" }] },
    { id: "last", label: "Last facet", entries: [{ id: "d", label: "D", description: "Description D" }] },
  ],
};
const sharedCatalogs = JSON.parse(await readFile(new URL("../generator/catalogs.json", import.meta.url), "utf8"));

test("shared catalog has usable unique facets and detailed options", () => {
  assert.equal(sharedCatalogs.fixed.wildstyle.id, "wildstyle");
  assert.ok(sharedCatalogs.fixed.wildstyle.description.length > 0);
  assert.ok(sharedCatalogs.facets.length > 0);
  const facetIds = new Set();
  for (const facet of sharedCatalogs.facets) {
    assert.equal(facetIds.has(facet.id), false);
    facetIds.add(facet.id);
    assert.ok(facet.entries.length > 0);
    const entryIds = new Set();
    for (const entry of facet.entries) {
      assert.equal(entryIds.has(entry.id), false);
      entryIds.add(entry.id);
      assert.ok(entry.label.length > 0);
      assert.ok(entry.description.length >= 300);
    }
  }
  assert.equal(facetIds.has("style"), false);
  assert.equal(facetIds.has("lighting"), false);
  assert.ok(facetIds.has("wildstyle-variation"));
  const variation = sharedCatalogs.facets.find((facet) => facet.id === "wildstyle-variation");
  assert.ok(variation.entries.length > 0);
  assert.ok(variation.entries.every((entry) => /wildstyle/i.test(`${entry.label} ${entry.description}`)));
  const theme = sharedCatalogs.facets.find((facet) => facet.id === "theme");
  assert.ok(theme);
  for (const id of ["solarpunk", "steampunk", "cyberpunk"]) assert.ok(theme.entries.some((entry) => entry.id === id));
});

test("every shared catalog facet and option can be counted", async () => {
  const markup = await readFile(new URL("../prompt-tool/app.js", import.meta.url), "utf8");
  assert.match(markup, /document\.createElement\("details"\)/);
  assert.match(markup, /facet\.label/);
  assert.match(markup, /entry\.label/);
  assert.match(markup, /entry\.description/);
  assert.match(markup, /catalogs\.fixed\.wildstyle/);
  assert.match(markup, /catalogs\.facets/);
  assert.match(markup, /facet\.label/);
  assert.match(markup, /entry\.label/);
  for (const facet of sharedCatalogs.facets) {
    assert.equal(enabledCount(facet.entries.length, facet.entries.length), facet.entries.length);
    assert.ok(facet.entries.every((entry) => entry.label && entry.description));
  }
});

test("enabled count is deterministic and bounded", () => {
  assert.equal(enabledCount(5, 3), 3);
  assert.equal(enabledCount(5, 0), 0);
  assert.equal(enabledCount(5, 9), 5);
  assert.equal(enabledCount(5, -1), 0);
});

test("real catalog choices all appear in generated output", () => {
  const enabled = new Set(sharedCatalogs.facets.flatMap((facet) => facet.entries.map((entry) => `${facet.id}:${entry.id}`)));
  const { selected, prompt } = generatePrompt(sharedCatalogs, enabled, () => 0);
  assert.equal(selected.length, sharedCatalogs.facets.length);
  assert.ok(prompt.includes(sharedCatalogs.fixed.wildstyle.description));
  for (const { entry } of selected) assert.ok(prompt.includes(entry.description));
});

test("selection samples only enabled entries and omits empty facets", () => {
  const recipe = selectRecipe(catalogs, new Set(["first:b", "last:d"]), () => 0.99);
  assert.deepEqual(recipe.map(({ facet, entry }) => [facet.id, entry.id]), [["first", "b"], ["last", "d"]]);
});

test("prompt includes selected descriptions and shared requirements", () => {
  const { prompt } = generatePrompt(catalogs, new Set(["first:a", "last:d"]), () => 0);
  assert.match(prompt, /Description A/);
  assert.match(prompt, /Description D/);
  assert.match(prompt, /Fixed wildstyle description/);
  assert.match(prompt, /Follow the live local time and weather supplied by the caller/);
  assert.match(prompt, /exactly uppercase ATLAS/);
  assert.match(prompt, /legible/);
  assert.match(prompt, /physically integrated/);
  assert.match(prompt, /photorealistic materials/);
  assert.match(prompt, /no extraneous text/);
  assert.doesNotMatch(prompt, /Empty facet/);
  assert.equal(SHARED_REQUIREMENTS.length > 0, true);
});

test("all-disabled selection reports an error", () => {
  assert.throws(() => generatePrompt(catalogs, new Set(), () => 0), /Enable at least one option/);
});

test("fixed wildstyle is included even when no option pool is enabled", () => {
  assert.throws(() => generatePrompt(catalogs, new Set(), () => 0), /Enable at least one option/);
  const result = generatePrompt(catalogs, new Set(["first:a"]), () => 0);
  assert.ok(result.prompt.includes(catalogs.fixed.wildstyle.description));
  assert.deepEqual(result.selected.map(({ facet }) => facet.id), ["first"]);
  assert.ok(result.prompt.includes(LIVE_CONTEXT_DIRECTIVE));
});

test("theme and wildstyle variation are visible and selectable", () => {
  const enabled = new Set(["theme:solarpunk", `${sharedCatalogs.facets.find((facet) => facet.id === "wildstyle-variation").id}:${sharedCatalogs.facets.find((facet) => facet.id === "wildstyle-variation").entries[0].id}`]);
  const { selected, prompt } = generatePrompt(sharedCatalogs, enabled, () => 0);
  assert.deepEqual(selected.map(({ facet }) => facet.id), ["theme", "wildstyle-variation"]);
  for (const { facet, entry } of selected) assert.ok(prompt.includes(`${facet.label}: ${entry.description}`));
  assert.doesNotMatch(prompt, /lighting variation|random lighting/i);
});
