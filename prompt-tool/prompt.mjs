export const SHARED_REQUIREMENTS = "The artwork spells exactly uppercase ATLAS in the correct order. All five letters must be clearly recognizable and legible. The painted artwork is physically integrated with and adheres to its believable supporting surface. Use photorealistic materials and credible physical geometry. Do not add any other words, lettering, tags, logos, captions, watermarks or marks; no extraneous text is allowed.";
export const LIVE_CONTEXT_DIRECTIVE = "Follow the live local time and weather supplied by the caller. Do not invent or conflict with lighting conditions; let lighting remain consistent with that supplied context.";

export function enabledCount(total, enabled) {
  return Math.max(0, Math.min(total, enabled));
}

export function selectRecipe(catalog, enabled, random = Math.random) {
  const selected = [];
  for (const facet of catalog.facets) {
    const pool = facet.entries.filter((entry) => enabled.has(`${facet.id}:${entry.id}`));
    if (pool.length) selected.push({ facet, entry: pool[Math.floor(random() * pool.length)] });
  }
  if (!selected.length) throw new Error("Enable at least one option before generating a prompt.");
  return selected;
}

export function generatePrompt(catalog, enabled, random = Math.random) {
  const selected = selectRecipe(catalog, enabled, random);
  const recipe = selected.map(({ facet, entry }) => `${facet.label}: ${entry.description}`).join("\n");
  return { selected, prompt: `Create a photorealistic architectural photograph.\nFIXED LETTERING (${catalog.fixed.wildstyle.label}): ${catalog.fixed.wildstyle.description}\nVISUAL RECIPE:\n${recipe}\nLIVE LOCAL CONTEXT: ${LIVE_CONTEXT_DIRECTIVE}\nSHARED REQUIREMENTS: ${SHARED_REQUIREMENTS}` };
}
