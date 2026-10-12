// Enter in a Budget cell moves down to the next one, as in a spreadsheet.
// Leaving the cell is what saves it (htmx's change trigger).
// A block, as app_shell.js declares names at the top level.
{
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !e.target.matches?.("[data-budget-cell]")) return;
    e.preventDefault();
    const cells = [...document.querySelectorAll("[data-budget-cell]")];
    const next = cells[cells.indexOf(e.target) + 1];
    if (next) next.focus();
    else e.target.blur();
  });
}
