// The server refuses files over the limit only after the browser has sent them
// all, so check the total as soon as files are picked or an Attachment is
// ticked for removal.
document.addEventListener("change", (event) => {
  const target = event.target;
  if (!target.matches("input[data-max-total-bytes], [name=remove_attachments]"))
    return;
  const form = target.form;
  const input = form.querySelector("input[data-max-total-bytes]");
  const picked = [...input.files].reduce((sum, file) => sum + file.size, 0);
  const removed = [
    ...form.querySelectorAll("input[name=remove_attachments]:checked"),
  ].reduce((sum, box) => sum + Number(box.dataset.size), 0);
  const total = Number(input.dataset.existingBytes) - removed + picked;
  const tooLarge = total > Number(input.dataset.maxTotalBytes);
  input.setCustomValidity(tooLarge ? input.dataset.tooLarge : "");
  input.reportValidity();
});
