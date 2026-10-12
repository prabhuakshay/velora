// The Transaction list's detail: beside the list on desktop, a sheet on
// phones and tablets. The selected row's detail is fetched into whichever
// shows it.
// A block, as app_shell.js declares the same names at the top level.
{
  const desktop = matchMedia("(min-width: 64rem)");
  const wide = () => desktop.matches;
  const current = () => document.querySelector("[data-transaction][aria-current]");
  let latest = 0;

  function idle(target) {
    target.removeAttribute("aria-busy");
    delete target.dataset.loading;
  }

  async function show(row) {
    current()?.removeAttribute("aria-current");
    row.setAttribute("aria-current", "true");
    const pane = document.querySelector("[data-transaction-pane]");
    const sheet = document.querySelector("[data-transaction-sheet-body]");
    const [target, other] = wide() ? [pane, sheet] : [sheet, pane];
    // The panel's delete dialog has a fixed id, so only one copy may be in the page.
    other.replaceChildren();
    idle(other);
    if (target === pane) pane.scrollTop = 0;
    // The sheet opens at once, and mustn't show the last Transaction's Delete meanwhile.
    else sheet.replaceChildren();
    const request = ++latest;
    target.setAttribute("aria-busy", "true");
    const slow = setTimeout(() => (target.dataset.loading = ""), 150);
    try {
      await htmx.ajax("GET", row.href, { source: row, target, swap: "innerHTML transition:false" });
    } catch {
      // Failed or aborted for a newer selection; the checks below tell which.
    }
    clearTimeout(slow);
    if (request !== latest) return;
    idle(target);
    const detail = target.querySelector(`[data-transaction-detail="${row.dataset.transaction}"]`);
    if (!detail) {
      const error = document.querySelector("[data-transaction-error]").content.cloneNode(true);
      error.querySelector("a").href = row.href;
      target.replaceChildren(error);
      return;
    }
    if (target === pane) {
      const { title, amount, date } = detail.dataset;
      document.querySelector("[data-transaction-announce]").textContent =
        `Showing ${[title.trim(), amount, date].filter(Boolean).join(", ")}`;
    }
  }

  // The shell's htmx config swaps in error pages; here show() says it failed instead.
  document.addEventListener("htmx:beforeSwap", (e) => {
    if (e.detail.requestConfig?.elt?.matches("[data-transaction]") && e.detail.xhr.status >= 400) {
      e.detail.shouldSwap = false;
    }
  });

  // Capture phase, so it runs before app_shell.js opens the sheet and can
  // stop it on desktop, where the detail pane shows the Transaction instead.
  document.addEventListener("click", (e) => {
    const row = e.target.closest("[data-transaction]");
    if (!row) return;
    // A modified click opens the Transaction's page in a new tab or window.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
      e.stopPropagation();
      return;
    }
    e.preventDefault();
    if (wide()) e.stopPropagation();
    show(row);
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
    if (wide()) show(next);
  });

  // A tap doesn't focus the row on iOS, so the dialog can't restore it itself.
  // Capture phase, as close doesn't bubble.
  document.addEventListener("close", (e) => {
    if (e.target.id === "transaction-sheet") current()?.focus();
  }, true);

  // Growing from phone to desktop: the pane was emptied when the sheet loaded.
  desktop.addEventListener("change", (e) => {
    const row = current();
    if (e.matches && row && !document.querySelector("[data-transaction-pane]")?.children.length) show(row);
  });
}
