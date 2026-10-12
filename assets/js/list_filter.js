// Filters a list page (Accounts, Parties, Tags) as you type; every row is already in the page.
// A block, as app_shell.js declares names at the top level.
{
  const rows = () => [...document.querySelectorAll("[data-filter-name]")];

  document.addEventListener("input", (e) => {
    const box = e.target.closest?.("[data-list-filter]");
    if (!box) return;
    const words = box.value.trim().toLowerCase().split(/\s+/);
    let shown = 0;
    for (const row of rows()) {
      row.hidden = !words.every((word) => row.dataset.filterName.includes(word));
      if (!row.hidden) shown++;
    }
    // A match among the hidden rows is no use folded away.
    const folded = document.querySelector("[data-filter-folded]");
    if (folded && box.value.trim()) {
      folded.open = [...folded.querySelectorAll("[data-filter-name]")].some((row) => !row.hidden);
    }
    for (const list of document.querySelectorAll("ul:has(> [data-filter-name])")) {
      list.hidden = !list.querySelector("[data-filter-name]:not([hidden])");
    }
    document.querySelector("[data-filter-none]").hidden = shown > 0;
  });

  // Enter opens the first match.
  document.addEventListener("keydown", (e) => {
    const box = e.target.closest?.("[data-list-filter]");
    if (!box || e.key !== "Enter") return;
    e.preventDefault();
    rows().find((row) => !row.hidden)?.querySelector("a")?.click();
  });

  // "/" jumps to the filter, like it does to the Quick Add box on the Drafts page.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.closest?.("input, textarea, select, [contenteditable]")) return;
    const box = document.querySelector("[data-list-filter]");
    if (!box) return;
    e.preventDefault();
    box.focus();
  });
}
