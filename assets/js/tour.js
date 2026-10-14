// Guided tours. The "?" menu names the page's tour and its Help page, and each
// highlighted element carries its step's number and text. A tour starts on its
// own the first time its page is opened, on any device: the user's record
// keeps which tours were seen. "Take the tour" in the "?" menu replays it.

let tour = null;

function escapeHTML(text) {
  const p = document.createElement("p");
  p.textContent = text;
  return p.innerHTML.replaceAll('"', "&quot;");
}

function steps(menu) {
  // No boxes means hidden at this width, like a sidebar-only element on a phone.
  const shown = [...document.querySelectorAll("[data-tour-step]")]
    .filter((el) => el.getClientRects().length)
    .sort((a, b) => a.dataset.tourStep - b.dataset.tourStep);
  return shown.map((el, i) => {
    let description = escapeHTML(el.dataset.tourText);
    if (i === shown.length - 1) description += `<a href="${escapeHTML(menu.dataset.tourHelp)}">Learn more in Help</a>`;
    return { element: el, popover: { description } };
  });
}

function startTour() {
  const menu = document.querySelector("[data-tour]");
  const list = menu && steps(menu);
  if (!list?.length) return false;
  tour?.destroy();
  tour = window.driver.js.driver({
    steps: list,
    animate: !matchMedia("(prefers-reduced-motion: reduce)").matches,
    popoverClass: "tour-card",
    showProgress: true,
    prevBtnText: "Back",
    nextBtnText: "Next",
    doneBtnText: "Done",
    // Boosts the Help link like any other, as driver.js adds it after htmx has looked.
    onPopoverRender: (popover) => htmx.process(popover.description),
    onDestroyed: () => {
      tour = null;
    },
  });
  tour.drive();
  return true;
}

function startUnseenTour() {
  const menu = document.querySelector("[data-tour]");
  if (!menu || "tourSeen" in menu.dataset) return;
  if (!startTour()) return;
  menu.dataset.tourSeen = "";
  // As the menu's, so it carries the page's CSRF header.
  htmx.ajax("POST", menu.dataset.tourSeenUrl, { source: menu, swap: "none" });
}

document.addEventListener("click", (e) => {
  if (!e.target.closest("[data-tour-start]")) return;
  document.getElementById("help-menu").hidePopover();
  startTour();
});

// A boosted page change swaps the whole body, which takes the tour's overlay
// with it but leaves driver.js thinking it is still running.
document.addEventListener("htmx:beforeSwap", (e) => {
  if (e.detail.target === document.body && e.detail.shouldSwap) tour?.destroy();
});
document.addEventListener("htmx:afterSettle", (e) => {
  if (e.detail.target === document.body) startUnseenTour();
});

startUnseenTour();
