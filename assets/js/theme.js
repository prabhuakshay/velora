// Light, dark or system theme. Loaded without defer so the theme lands before
// first paint. A per-browser choice, so it lives in localStorage.

const root = document.documentElement;
const darkQuery = matchMedia("(prefers-color-scheme: dark)");

function readTheme() {
  try {
    return localStorage.getItem("theme") || "system";
  } catch {
    return "system";
  }
}

function applyTheme(pref = readTheme()) {
  const dark = pref === "dark" || (pref === "system" && darkQuery.matches);
  root.dataset.themePref = pref;
  root.dataset.theme = dark ? "dark" : "light";
}

function setTheme(pref) {
  try {
    localStorage.setItem("theme", pref);
  } catch {}
  if (!document.startViewTransition) return applyTheme(pref);
  // Marks the transition as a theme change, so app.css slows the crossfade
  // that page changes keep short.
  root.dataset.themeSwitching = "";
  const transition = document.startViewTransition(() => applyTheme(pref));
  transition.finished.finally(() => delete root.dataset.themeSwitching);
}

applyTheme();
darkQuery.addEventListener("change", () => applyTheme());

const CYCLE = { light: "dark", dark: "system", system: "light" };
document.addEventListener("click", (e) => {
  const set = e.target.closest("[data-theme-set]");
  if (set) setTheme(set.dataset.themeSet);
  if (e.target.closest("[data-theme-cycle]")) setTheme(CYCLE[readTheme()]);
});
