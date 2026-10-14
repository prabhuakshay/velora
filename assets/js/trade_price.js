// The Trade Price line on the Investment Event and Draft forms: Amount ÷ units
// as the user types, to compare with the NAV or contract note before saving.
{
  const formats = {
    indian: new Intl.NumberFormat("en-IN", { minimumFractionDigits: 4, maximumFractionDigits: 4 }),
    international: new Intl.NumberFormat("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 }),
  };

  function updateTradePrice() {
    const line = document.querySelector("[data-trade-price]");
    if (!line || "private" in line.dataset) return;
    const units = Number(document.getElementById(line.dataset.units)?.value);
    const amount = Number(document.getElementById(line.dataset.amount)?.value);
    const format = formats[line.dataset.numberFormat] ?? formats.indian;
    line.textContent = units > 0 && amount > 0 ? `₹${format.format(amount / units)}` : "—";
  }

  document.addEventListener("input", updateTradePrice);
  document.addEventListener("htmx:load", updateTradePrice);
  // A boosted visit adds this script after that page's htmx:load has fired.
  updateTradePrice();
}
