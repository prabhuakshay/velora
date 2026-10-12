// The Transaction form's running Total and its file drop zone.
// A block, as app_shell.js declares names at the top level.
{
  const formats = {
    indian: new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    international: new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  };

  function updateTotal() {
    const total = document.querySelector("[data-split-total]");
    if (!total) return;
    const kept = [...document.querySelectorAll("#splits > fieldset")].filter(
      (split) => !split.querySelector("[name$='-DELETE']:checked"),
    );
    const amounts = kept.map((split) => Number(split.querySelector("[name$='-amount']")?.value) || 0);
    // A Draft may wait without an amount; flag each gap rather than total it as zero.
    const draft = "draft" in total.dataset;
    let missing = false;
    for (const input of document.querySelectorAll("#splits [name$='-amount']")) {
      const gap = draft && input.value === "" && kept.includes(input.closest("fieldset"));
      input.classList.toggle("draft-gap", gap);
      missing ||= gap;
    }
    // A Schedule's blank amount is open on purpose, so it reads as Open amount, not a gap.
    const open = "open" in total.dataset && kept.some((split) => split.querySelector("[name$='-amount']")?.value === "");
    total.classList.toggle("text-amber-700", missing);
    total.classList.toggle("text-slate-500", open);
    if (missing) {
      total.textContent = "Missing";
    } else if (open) {
      total.textContent = "Open amount";
    } else if (!("private" in total.dataset)) {
      const format = formats[total.dataset.numberFormat] ?? formats.indian;
      total.textContent = `₹${format.format(amounts.reduce((sum, a) => sum + a, 0))}`;
    }
    const count = document.querySelector("[data-split-count]");
    if (count) count.textContent = `Across ${kept.length} Split${kept.length === 1 ? "" : "s"}`;
  }

  function showPicked(input) {
    const names = input.closest("[data-file-drop]")?.querySelector("[data-file-names]");
    if (!names) return;
    const files = [...input.files];
    names.hidden = !files.length;
    names.classList.toggle("hidden", !files.length);
    names.textContent = files.length === 1 ? files[0].name : `${files.length} files picked`;
    names.title = files.map((f) => f.name).join("\n");
  }

  document.addEventListener("input", (e) => {
    if (e.target.closest("#splits")) updateTotal();
  });
  document.addEventListener("change", (e) => {
    if (e.target.closest("#splits")) updateTotal();
    if (e.target.matches("[data-file-drop] input[type=file]")) showPicked(e.target);
  });
  // Page loads, boosted page swaps and added Split rows.
  document.addEventListener("htmx:load", updateTotal);
  // Only form pages load this script, and a boosted visit adds it after that
  // page's htmx:load has fired.
  updateTotal();

  for (const [type, dragging] of [["dragenter", true], ["dragleave", false], ["drop", false]]) {
    document.addEventListener(type, (e) => {
      e.target.closest?.("[data-file-drop]")?.classList.toggle("is-dragging", dragging);
    });
  }
}
