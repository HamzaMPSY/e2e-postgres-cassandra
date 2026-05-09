const els = {
  statusDot: document.querySelector("#statusDot"),
  statusText: document.querySelector("#statusText"),
  refreshButton: document.querySelector("#refreshButton"),
  grossRevenue: document.querySelector("#grossRevenue"),
  orderLines: document.querySelector("#orderLines"),
  paymentAmount: document.querySelector("#paymentAmount"),
  supportCases: document.querySelector("#supportCases"),
  revenueTotal: document.querySelector("#revenueTotal"),
  paymentCount: document.querySelector("#paymentCount"),
  supportCount: document.querySelector("#supportCount"),
  openAmount: document.querySelector("#openAmount"),
  revenueChart: document.querySelector("#revenueChart"),
  paymentList: document.querySelector("#paymentList"),
  supportList: document.querySelector("#supportList"),
  cashTable: document.querySelector("#cashTable"),
};

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const number = new Intl.NumberFormat("en-US");

async function loadDashboard() {
  setStatus("Loading", "loading");
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    render(data);
    setStatus("Live", "ready");
  } catch (error) {
    setStatus("Unavailable", "failed");
    renderError(error);
  }
}

function setStatus(text, state) {
  els.statusText.textContent = text;
  els.statusDot.className = `status-dot ${state}`;
}

function render(data) {
  const summary = data.summary || {};
  els.grossRevenue.textContent = money.format(summary.grossRevenue || 0);
  els.orderLines.textContent = number.format(summary.orderLines || 0);
  els.paymentAmount.textContent = money.format(summary.paymentAmount || 0);
  els.supportCases.textContent = number.format(summary.supportCases || 0);
  els.revenueTotal.textContent = money.format(summary.grossRevenue || 0);
  els.paymentCount.textContent = `${number.format(summary.paymentCount || 0)} payments`;
  els.supportCount.textContent = `${number.format(summary.supportCases || 0)} cases`;
  els.openAmount.textContent = `${money.format(summary.openAmount || 0)} open`;

  renderRevenue(data.revenueByDay || []);
  renderPayments(data.paymentHealth || []);
  renderSupport(data.supportRisk || []);
  renderCash(data.orderToCash || []);
}

function renderRevenue(rows) {
  const clean = rows.filter((row) => !row.error);
  if (!clean.length) {
    els.revenueChart.innerHTML = empty("No revenue facts yet.");
    return;
  }

  const max = Math.max(...clean.map((row) => Number(row.gross_revenue || 0)), 1);
  els.revenueChart.innerHTML = clean
    .map((row) => {
      const value = Number(row.gross_revenue || 0);
      const width = Math.max((value / max) * 100, 2);
      return `
        <div class="bar-row">
          <span>${escapeHtml(row.order_day)}</span>
          <span class="bar-track"><span class="bar-fill" style="--bar-width: ${width}%"></span></span>
          <strong>${money.format(value)}</strong>
        </div>
      `;
    })
    .join("");
}

function renderPayments(rows) {
  renderStatusList(
    els.paymentList,
    rows,
    "No payment facts yet.",
    (row) => `
      <div class="status-label">
        <strong>${escapeHtml(row.payment_status || "unknown")}</strong>
        <span class="tag">${escapeHtml(row.payment_day || "")}</span>
      </div>
      <div class="status-value">${money.format(Number(row.amount || 0))}</div>
    `
  );
}

function renderSupport(rows) {
  renderStatusList(
    els.supportList,
    rows,
    "No support cases yet.",
    (row) => `
      <div class="status-label">
        <strong>${escapeHtml(row.priority || "unknown")}</strong>
        <span class="tag">${escapeHtml(row.status || "open")}</span>
        <span class="tag">${escapeHtml(row.opened_day || "")}</span>
      </div>
      <div class="status-value">${number.format(Number(row.ticket_count || 0))}</div>
    `
  );
}

function renderStatusList(target, rows, emptyMessage, template) {
  const error = rows.find((row) => row.error);
  if (error) {
    target.innerHTML = `<p class="error">${escapeHtml(error.error)}</p>`;
    return;
  }
  if (!rows.length) {
    target.innerHTML = empty(emptyMessage);
    return;
  }
  target.innerHTML = rows
    .slice(0, 8)
    .map((row) => `<div class="status-item">${template(row)}</div>`)
    .join("");
}

function renderCash(rows) {
  const clean = rows.filter((row) => !row.error);
  if (!clean.length) {
    els.cashTable.innerHTML = `<tr><td colspan="5" class="empty">No order-to-cash rows yet.</td></tr>`;
    return;
  }

  els.cashTable.innerHTML = clean
    .map((row) => `
      <tr>
        <td>${shortId(row.order_id)}</td>
        <td>${shortId(row.customer_id)}</td>
        <td class="numeric">${money.format(Number(row.ordered_amount || 0))}</td>
        <td class="numeric">${money.format(Number(row.captured_amount || 0))}</td>
        <td class="numeric">${money.format(Number(row.open_amount || 0))}</td>
      </tr>
    `)
    .join("");
}

function renderError(error) {
  els.revenueChart.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
}

function empty(message) {
  return `<p class="empty">${message}</p>`;
}

function shortId(value) {
  if (!value) return "-";
  const text = String(value);
  return escapeHtml(text.length > 14 ? `${text.slice(0, 8)}...${text.slice(-4)}` : text);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.refreshButton.addEventListener("click", loadDashboard);
loadDashboard();
setInterval(loadDashboard, 30000);
