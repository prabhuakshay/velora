// The server refuses files over the limit only after the browser has sent them
// all, so check the total as soon as files are picked.
document.addEventListener("change", (event) => {
  const input = event.target;
  if (!input.matches("input[data-max-total-bytes]")) return;
  const picked = [...input.files].reduce((sum, file) => sum + file.size, 0);
  const total = Number(input.dataset.existingBytes) + picked;
  const tooLarge = total > Number(input.dataset.maxTotalBytes);
  input.setCustomValidity(tooLarge ? input.dataset.tooLarge : "");
  input.reportValidity();
});
