import { enabledCount, generatePrompt } from "./prompt.mjs";

const catalogElement = document.querySelector("#catalog");
const output = document.querySelector("#output");
const selection = document.querySelector("#selection");
const status = document.querySelector("#status");
let catalogs = [];
let lastSelected = [];

function showSelection(items) {
  selection.replaceChildren();
  if (!items.length) {
    const message = document.createElement("p");
    message.textContent = "Generate a prompt to see your selections.";
    selection.append(message);
    return;
  }
  const list = document.createElement("ul");
  for (const { facet, entry } of items) {
    const item = document.createElement("li");
    item.textContent = `${facet.label}: ${entry.label}`;
    list.append(item);
  }
  selection.append(list);
}

function renderCatalog() {
  catalogElement.replaceChildren();
  for (const facet of catalogs) {
    const disclosure = document.createElement("details");
    disclosure.className = "facet";
    const summary = document.createElement("summary");
    const facetName = document.createElement("span");
    facetName.textContent = facet.label;
    const count = document.createElement("span");
    count.className = "facet-count";
    count.dataset.count = facet.id;
    count.setAttribute("aria-live", "polite");
    count.textContent = `${facet.entries.length} / ${facet.entries.length} enabled`;
    summary.append(facetName, count);
    disclosure.append(summary);
    const options = document.createElement("div");
    options.className = "facet-options";
    for (const entry of facet.entries) {
      const card = document.createElement("div");
      card.className = "option";
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = true;
      checkbox.dataset.option = `${facet.id}:${entry.id}`;
      checkbox.addEventListener("change", updateCounts);
      const descriptionId = `option-${facet.id}-${entry.id}-description`;
      checkbox.setAttribute("aria-describedby", descriptionId);
      const title = document.createElement("strong");
      title.textContent = entry.label;
      label.append(checkbox, title);
      const description = document.createElement("p");
      description.id = descriptionId;
      description.textContent = entry.description;
      card.append(label, description);
      options.append(card);
    }
    disclosure.append(options);
    catalogElement.append(disclosure);
  }
  updateCounts();
}

function updateCounts() {
  for (const facet of catalogs) {
    const inputs = [...document.querySelectorAll("input[data-option]")].filter((input) => input.dataset.option.startsWith(`${facet.id}:`));
    const enabled = enabledCount(inputs.length, inputs.filter((input) => input.checked).length);
    const count = catalogElement.querySelector(`[data-count="${facet.id}"]`);
    if (count) count.textContent = `${enabled} / ${inputs.length} enabled`;
  }
}

function enabledOptions() {
  return new Set([...document.querySelectorAll("input[data-option]:checked")].map((input) => input.dataset.option));
}

document.querySelector("#generate").addEventListener("click", () => {
  try {
    const result = generatePrompt(catalogs, enabledOptions());
    output.value = result.prompt;
    lastSelected = result.selected;
    showSelection(lastSelected);
    status.textContent = "Prompt generated.";
  } catch (error) {
    status.textContent = error.message;
  }
});

document.querySelector("#reset").addEventListener("click", () => {
  document.querySelectorAll("input[data-option]").forEach((input) => { input.checked = true; });
  updateCounts();
  status.textContent = "All options enabled.";
});

document.querySelector("#copy").addEventListener("click", async () => {
  if (!output.value) {
    status.textContent = "Generate a prompt before copying.";
    return;
  }
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(output.value);
      status.textContent = "Prompt copied to clipboard.";
      return;
    } catch {
      status.textContent = "Clipboard access failed. Select the prompt below and copy it manually.";
    }
  } else {
    status.textContent = "Clipboard is unavailable. Select the prompt below and copy it manually.";
  }
  output.focus();
  output.select();
});

try {
  const response = await fetch("./catalogs.json");
  if (!response.ok) throw new Error(`Catalog request failed (${response.status}).`);
  catalogs = await response.json();
  if (!Array.isArray(catalogs)) throw new Error("Catalog data has an invalid format.");
  renderCatalog();
} catch (error) {
  catalogElement.replaceChildren();
  const message = document.createElement("p");
  message.textContent = `Unable to load the visual catalog: ${error.message}`;
  catalogElement.append(message);
  document.querySelector("#generate").disabled = true;
}
