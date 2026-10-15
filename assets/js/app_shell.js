// The shell's loading bar, the More and Quick Add sheets' open/close and their
// swipe-down-to-close, and the service worker that makes Velora installable.

// Only boosted page loads, not in-page partials like Quick Add polling.
document.addEventListener("htmx:beforeRequest", (e) => {
  if (e.detail.boosted) document.documentElement.dataset.loading = "";
});
for (const done of ["htmx:afterSwap", "htmx:responseError", "htmx:sendError"]) {
  document.addEventListener(done, () => delete document.documentElement.dataset.loading);
}

// Animated in JS rather than CSS @starting-style, which older iOS Safari ignores.
const EASE = "cubic-bezier(0.32, 0.72, 0, 1)";
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const wide = () => matchMedia("(min-width: 48rem)").matches;

function fadeBackdrop(dialog, from, to, duration) {
  dialog.animate({ opacity: [from, to] }, { duration, easing: "ease-out", pseudoElement: "::backdrop", fill: "forwards" });
}

function openDialog(dialog) {
  dialog.showModal();
  dialog.querySelector("[data-autofocus]")?.focus();
  if (reduced()) return;
  const duration = wide() ? 200 : 500;
  const frames = wide()
    ? [{ opacity: 0, transform: "scale(0.95)" }, { opacity: 1, transform: "scale(1)" }]
    : [{ transform: "translateY(100%)" }, { transform: "translateY(0)" }];
  dialog.animate(frames, { duration, easing: EASE });
  fadeBackdrop(dialog, 0, 1, duration);
}

function closeDialog(dialog, onClosed = () => {}) {
  if (!dialog.open || dialog.dataset.closing) return;
  if (reduced()) {
    dialog.close();
    onClosed();
    return;
  }
  dialog.dataset.closing = "";
  // A swipe leaves the sheet part-way down; carry on from there.
  const from = dialog.style.transform || (wide() ? "scale(1)" : "translateY(0)");
  const duration = wide() ? 150 : 300;
  const frames = wide()
    ? [{ opacity: 1, transform: from }, { opacity: 0, transform: "scale(0.95)" }]
    : [{ transform: from }, { transform: "translateY(100%)" }];
  dialog.style.transform = "";
  const animation = dialog.animate(frames, { duration, easing: EASE, fill: "forwards" });
  fadeBackdrop(dialog, 1, 0, duration);
  animation.onfinish = () => {
    dialog.close();
    dialog.getAnimations({ subtree: true }).forEach((a) => a.cancel());
    delete dialog.dataset.closing;
    onClosed();
  };
}

document.addEventListener("click", (e) => {
  const opener = e.target.closest("[data-dialog-open]");
  // A link opener's href is the page to use without JS.
  if (opener) {
    e.preventDefault();
    openDialog(document.getElementById(opener.dataset.dialogOpen));
  }
  // The dialog clicked in, not the first open one, as a dialog can open over another.
  const dialog = e.target.closest("dialog[data-dialog][open]");
  // A click on the dialog element itself is a click on its backdrop. A
  // persistent dialog holds a form, so only its close buttons close it.
  const stray = dialog && !("persistent" in dialog.dataset) && (e.target === dialog || e.target.closest("a"));
  if (dialog && (stray || e.target.closest("[data-dialog-close]"))) {
    closeDialog(dialog);
  }
});

// Escape: animate out instead of the browser's instant close.
document.addEventListener("cancel", (e) => {
  if (!e.target.matches("dialog[data-dialog]")) return;
  e.preventDefault();
  closeDialog(e.target);
}, true);

// Only when the sheet is scrolled to the top, so the swipe doesn't fight scrolling.
let sheet = null;
let startY = 0;
let startTime = 0;
let dragged = 0;
document.addEventListener("touchstart", (e) => {
  const s = e.target.closest("dialog[data-sheet][open]");
  if (!s || s.scrollTop > 0 || s.dataset.closing) return;
  sheet = s;
  startY = e.touches[0].clientY;
  startTime = e.timeStamp;
  dragged = 0;
}, { passive: true });
document.addEventListener("touchmove", (e) => {
  if (!sheet) return;
  dragged = Math.max(0, e.touches[0].clientY - startY);
  if (dragged > 0) {
    e.preventDefault();
    sheet.style.transform = `translateY(${dragged}px)`;
  }
}, { passive: false });
document.addEventListener("touchend", (e) => {
  if (!sheet) return;
  const s = sheet;
  sheet = null;
  if (!dragged) return;
  const flicked = dragged > 30 && dragged / (e.timeStamp - startTime) > 0.5;
  if (dragged > s.offsetHeight / 3 || flicked) {
    closeDialog(s);
  } else {
    const from = s.style.transform;
    s.style.transform = "";
    s.animate([{ transform: from }, { transform: "translateY(0)" }], { duration: 300, easing: EASE });
  }
});

// The floating Quick Add sheet: the server says when it's sent, and a request
// that fails, as when offline or with an error page, leaves the text in place
// to retry. "Sent" waits for the sheet to close, as the modal makes the
// status region inert until then.
document.addEventListener("quick-add-sent", (e) => {
  const dialog = e.target.closest?.("dialog[data-dialog]");
  if (!dialog) return;
  closeDialog(dialog, () => {
    const sent = document.getElementById("quick-add-sent").content.cloneNode(true);
    document.getElementById("quick-add-status").replaceChildren(sent);
  });
});
const sendError = (e) => e.target.closest?.("[data-quick-add]")?.querySelector("[data-send-error]");
document.addEventListener("htmx:beforeRequest", (e) => {
  const error = sendError(e);
  if (error) error.hidden = true;
});
document.addEventListener("htmx:sendError", (e) => {
  const error = sendError(e);
  if (error) error.hidden = false;
});
document.addEventListener("htmx:beforeSwap", (e) => {
  const error = sendError(e);
  if (error && e.detail.xhr.status >= 300) {
    e.detail.shouldSwap = false;
    error.hidden = false;
  }
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");

// "/" jumps to the Quick Add box on the Drafts page.
document.addEventListener("keydown", (e) => {
  if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.target.closest?.("input, textarea, select, [contenteditable]")) return;
  const box = document.getElementById("quick-add-text");
  if (!box) return;
  e.preventDefault();
  box.focus();
});

// The "?" menu drops from its button, right-aligned to it. Popovers sit in the
// top layer, out of the page's flow, so they can't be placed by CSS alone.
document.addEventListener("beforetoggle", (e) => {
  if (e.newState !== "open" || !e.target.matches?.("[data-help-menu]")) return;
  const button = document.querySelector(`[popovertarget="${e.target.id}"]`).getBoundingClientRect();
  e.target.style.top = `${button.bottom + 4}px`;
  e.target.style.right = `${document.documentElement.clientWidth - button.right}px`;
}, true);
