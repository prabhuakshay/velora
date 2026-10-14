// The Instrument field: lists the known Instruments matching what's typed, fills in the one
// picked, and opens Add new when none fits. Without it the field takes an exact ISIN or name.
{
  let timer;
  let asked = 0;

  const parts = (field) => ({
    query: field.querySelector("[data-instrument-query]"),
    matches: field.querySelector("[data-instrument-matches]"),
    adding: field.querySelector('input[type="checkbox"]'),
    added: field.querySelector("[data-instrument-new]"),
  });

  function showAdding(field) {
    const { adding, added } = parts(field);
    // Errors on Add new's parts, from the older ISIN-and-name way, must stay in view.
    added.hidden = !adding.checked && !("errors" in added.dataset);
  }

  function close(field) {
    const { matches } = parts(field);
    matches.hidden = true;
    matches.replaceChildren();
  }

  async function search(field) {
    const { query, matches } = parts(field);
    const mine = ++asked;
    if (!query.value.trim()) return close(field);
    const url = `${field.dataset.instrumentSearch}?q=${encodeURIComponent(query.value)}`;
    const response = await fetch(url);
    // A slower answer to an earlier keystroke mustn't replace a newer one.
    if (!response.ok || mine !== asked) return;
    matches.innerHTML = await response.text();
    matches.hidden = false;
  }

  document.addEventListener("input", (e) => {
    const field = e.target.closest?.("[data-instrument-field]");
    if (!field) return;
    if (e.target.matches("[data-instrument-query]")) {
      clearTimeout(timer);
      timer = setTimeout(() => search(field), 200);
    } else {
      showAdding(field);
    }
  });

  document.addEventListener("click", (e) => {
    const field = e.target.closest?.("[data-instrument-field]");
    for (const other of document.querySelectorAll("[data-instrument-field]")) {
      if (other !== field) close(other);
    }
    if (!field) return;
    const { query, adding, added } = parts(field);
    const choice = e.target.closest("[data-instrument-choice]");
    const add = e.target.closest("[data-instrument-add]");
    if (choice) {
      query.value = choice.dataset.instrumentChoice;
      adding.checked = false;
    } else if (add) {
      query.value = "";
      adding.checked = true;
      const name = added.querySelector('input[type="text"]');
      name.value = add.dataset.instrumentAdd;
      name.focus();
    } else {
      return;
    }
    showAdding(field);
    close(field);
  });

  document.addEventListener("keydown", (e) => {
    const field = e.target.closest?.("[data-instrument-field]");
    if (field && e.key === "Escape") close(field);
  });

  function setUp() {
    document.querySelectorAll("[data-instrument-field]").forEach(showAdding);
  }

  document.addEventListener("htmx:load", setUp);
  // A boosted visit adds this script after that page's htmx:load has fired.
  setUp();
}
