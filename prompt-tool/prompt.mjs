export const SHARED_REQUIREMENTS = "The artwork spells exactly uppercase ATLAS in the correct order. All five letters must be clearly recognizable and legible. The painted artwork is physically integrated with and adheres to its believable supporting surface. Use photorealistic materials and credible physical geometry. Do not add any other words, lettering, tags, logos, captions, watermarks or marks; no extraneous text is allowed.";

export function enabledCount(total, enabled) {
  return Math.max(0, Math.min(total, enabled));
}

export function selectRecipe(catalogs, enabled, random = Math.random) {
  const selected = [];
  for (const facet of catalogs) {
    const pool = facet.entries.filter((entry) => enabled.has(`${facet.id}:${entry.id}`));
    if (pool.length) selected.push({ facet, entry: pool[Math.floor(random() * pool.length)] });
  }
  if (!selected.length) throw new Error("Enable at least one option before generating a prompt.");
  return selected;
}

export function generatePrompt(catalogs, enabled, random = Math.random) {
  const selected = selectRecipe(catalogs, enabled, random);
  const recipe = selected.map(({ facet, entry }) => `${facet.label}: ${entry.description}`).join("\n");
  return { selected, prompt: `Create a photorealistic architectural photograph.\nVISUAL RECIPE:\n${recipe}\nSHARED REQUIREMENTS: ${SHARED_REQUIREMENTS}` };
}
