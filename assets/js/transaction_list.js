// The Transaction list's detail: beside the list on desktop, a sheet on
// phones. Every row's detail is already in the page; this only shows one.
// A block, as app_shell.js declares the same names at the top level.
{
  const wide = () => matchMedia("(min-width: 48rem)").matches;

  function select(row) {
    for (const r of document.querySelectorAll("[data-transaction][aria-current]")) r.removeAttribute("aria-current");
    row.setAttribute("aria-current", "true");
    for (const d of document.querySelectorAll("[data-transaction-detail]")) {
      d.hidden = d.dataset.transactionDetail !== row.dataset.transaction;
    }
    document.querySelector("[data-transaction-pane]").scrollTop = 0;
  }

  // Capture phase, so it runs before app_shell.js opens the sheet and can
  // stop it on desktop, where the detail pane shows the Transaction instead.
  document.addEventListener("click", (e) => {
    const row = e.target.closest("[data-transaction]");
    if (!row) return;
    select(row);
    if (wide()) {
      e.stopPropagation();
      return;
    }
    const detail = document.querySelector(`[data-transaction-detail="${row.dataset.transaction}"]`);
    document.querySelector("[data-transaction-sheet-body]").replaceChildren(...detail.cloneNode(true).childNodes);
  }, true);

  // Up/down or j/k move through the list from a focused row.
  document.addEventListener("keydown", (e) => {
    const row = e.target.closest?.("[data-transaction]");
    const step = { ArrowDown: 1, j: 1, ArrowUp: -1, k: -1 }[e.key];
    if (!row || !step || e.metaKey || e.ctrlKey || e.altKey) return;
    e.preventDefault();
    const rows = [...document.querySelectorAll("[data-transaction]")];
    const next = rows[rows.indexOf(row) + step];
    if (!next) return;
    next.focus();
    if (wide()) select(next);
  });
}
