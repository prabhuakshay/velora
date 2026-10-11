// Opens and closes the shell's dialogs (the More sheet), including swipe-down-to-close.
document.addEventListener("click", (e) => {
  const opener = e.target.closest("[data-dialog-open]");
  if (opener) document.getElementById(opener.dataset.dialogOpen)?.showModal();
  const dialog = document.querySelector("dialog[data-dialog][open]");
  // A click on the dialog element itself is a click on its backdrop.
  if (dialog && (e.target === dialog || e.target.closest("[data-dialog-close]") || e.target.closest("dialog[data-dialog] a"))) {
    dialog.close();
  }
});

// Only when the sheet is scrolled to the top, so the swipe doesn't fight scrolling.
let sheet = null;
let startY = 0;
let startTime = 0;
let dragged = 0;
document.addEventListener("touchstart", (e) => {
  const s = e.target.closest("dialog[data-sheet][open]");
  if (!s || s.scrollTop > 0) return;
  sheet = s;
  startY = e.touches[0].clientY;
  startTime = e.timeStamp;
  dragged = 0;
  sheet.style.transition = "none";
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
  const flicked = dragged > 30 && dragged / (e.timeStamp - startTime) > 0.5;
  s.style.transition = "transform 200ms ease-out";
  if (dragged > s.offsetHeight / 3 || flicked) {
    s.style.transform = "translateY(100%)";
    setTimeout(() => {
      s.close();
      s.style.transform = "";
      s.style.transition = "";
    }, 200);
  } else {
    s.style.transform = "";
  }
});
