// The Instrument page's Price chart: hover or tap for a day's Price, and the
// 1M, 6M, 1Y and All buttons to zoom. Redraws the server's SVG from the
// Prices the page embeds; Privacy Mode embeds none, so nothing runs there.
{
  const formats = {
    indian: new Intl.NumberFormat("en-IN", { minimumFractionDigits: 4, maximumFractionDigits: 4 }),
    international: new Intl.NumberFormat("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 }),
  };
  // Dates are calendar days, so format them in UTC to keep the day as stored.
  const dayFormat = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const monthFormat = new Intl.DateTimeFormat("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });

  function setUp(chart) {
    const data = document.getElementById("price-chart-data");
    if (!data || chart.dataset.ready) return;
    chart.dataset.ready = "";
    const prices = JSON.parse(data.textContent).map(([day, price]) => ({ day: new Date(`${day}T00:00:00Z`), price: Number(price) }));
    const format = formats[chart.dataset.numberFormat] ?? formats.indian;
    const svg = chart.querySelector("svg");
    const [, , width, height] = svg.getAttribute("viewBox").split(" ").map(Number);
    const plot = chart.querySelector("[data-price-chart-plot]");
    const line = chart.querySelector("[data-price-chart-line]");
    const area = chart.querySelector("[data-price-chart-area]");
    const cursor = chart.querySelector("[data-price-chart-cursor]");
    const readout = chart.querySelector("[data-price-chart-readout]");
    const start = chart.querySelector("[data-price-chart-start]");
    const ranges = chart.querySelector("[data-price-chart-ranges]");
    let shown = prices;

    // Same geometry as apps/home/charts.py line(), so the first draw matches.
    const x = (i) => (width / Math.max(shown.length - 1, 1)) * i;

    function draw(months) {
      if (months === "all") {
        shown = prices;
      } else {
        const cutoff = new Date(prices.at(-1).day);
        cutoff.setUTCMonth(cutoff.getUTCMonth() - Number(months));
        shown = prices.filter((p) => p.day >= cutoff);
        if (shown.length < 2) shown = prices.slice(-2);
      }
      const low = Math.min(...shown.map((p) => p.price));
      const high = Math.max(...shown.map((p) => p.price));
      const y = (price) => (high === low ? height / 2 : height - ((price - low) / (high - low)) * height);
      const points = shown.map((p, i) => `${x(i).toFixed(1)},${y(p.price).toFixed(1)}`).join(" ");
      line.setAttribute("points", points);
      area.setAttribute("points", `0,${height} ${points} ${width},${height}`);
      start.textContent = (months === "all" ? monthFormat : dayFormat).format(shown[0].day);
      hide();
    }

    function show(event) {
      const box = plot.getBoundingClientRect();
      const fraction = Math.min(Math.max((event.clientX - box.left) / box.width, 0), 1);
      const i = Math.round(fraction * (shown.length - 1));
      cursor.setAttribute("x1", x(i));
      cursor.setAttribute("x2", x(i));
      cursor.setAttribute("visibility", "visible");
      readout.textContent = `${dayFormat.format(shown[i].day)} · ₹${format.format(shown[i].price)}`;
    }

    function hide() {
      cursor.setAttribute("visibility", "hidden");
      readout.textContent = "";
    }

    plot.addEventListener("pointermove", show);
    plot.addEventListener("pointerdown", show);
    // A finger lifting also "leaves", which would clear a tap at once.
    plot.addEventListener("pointerleave", (event) => event.pointerType !== "touch" && hide());
    ranges.addEventListener("click", (event) => {
      const button = event.target.closest("[data-range]");
      if (!button) return;
      for (const other of ranges.querySelectorAll("[data-range]")) other.setAttribute("aria-pressed", String(other === button));
      draw(button.dataset.range);
    });
    ranges.hidden = false;
  }

  function setUpAll() {
    for (const chart of document.querySelectorAll("[data-price-chart]")) setUp(chart);
  }

  document.addEventListener("htmx:load", setUpAll);
  // A boosted visit adds this script after that page's htmx:load has fired.
  setUpAll();
}
