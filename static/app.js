function fmtNum(x, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return "";
  return Number(x).toFixed(digits);
}

function toPct(x) {
  if (x === null || x === undefined || Number.isNaN(x)) return "";
  return (Number(x) * 100).toFixed(4);
}

function todayISO() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function buildRow(row) {
  const tr = document.createElement("tr");
  tr.dataset.isin = row.isin;

  const staticCells = [
    row.category,
    row.name,
    row.isin,
    row.redemption_date,
    row.first_issue_date,
    row.dividend_dates,
    row.total_amount_in_issue_million === null ? "" : fmtNum(row.total_amount_in_issue_million, 3),
    fmtNum(row.coupon_rate_percent, 3),
  ];
  for (const value of staticCells) {
    const td = document.createElement("td");
    td.textContent = String(value);
    tr.appendChild(td);
  }

  const purchaseDateTd = document.createElement("td");
  const purchaseDateInput = document.createElement("input");
  purchaseDateInput.type = "date";
  purchaseDateInput.className = "purchase-date";
  purchaseDateInput.value = todayISO();
  purchaseDateTd.appendChild(purchaseDateInput);
  tr.appendChild(purchaseDateTd);

  const priceTd = document.createElement("td");
  const priceInput = document.createElement("input");
  priceInput.type = "number";
  priceInput.step = "0.0001";
  priceInput.min = "0";
  priceInput.placeholder = "e.g. 99.50";
  priceInput.className = "price";
  priceTd.appendChild(priceInput);
  tr.appendChild(priceTd);

  const taxTd = document.createElement("td");
  const taxInput = document.createElement("input");
  taxInput.type = "number";
  taxInput.step = "0.01";
  taxInput.min = "0";
  taxInput.max = "99.99";
  taxInput.placeholder = "e.g. 40";
  taxInput.className = "tax";
  taxTd.appendChild(taxInput);
  tr.appendChild(taxTd);

  const dirtyTd = document.createElement("td");
  dirtyTd.className = "dirty";
  tr.appendChild(dirtyTd);

  const yieldTd = document.createElement("td");
  yieldTd.className = "yield";
  tr.appendChild(yieldTd);

  const taxedYieldTd = document.createElement("td");
  taxedYieldTd.className = "taxed-yield";
  tr.appendChild(taxedYieldTd);

  const taxEqTd = document.createElement("td");
  taxEqTd.className = "taxeq";
  tr.appendChild(taxEqTd);

  let seq = 0;
  async function recalc() {
    const localSeq = ++seq;
    const price = Number(priceInput.value);
    const taxPct = Number(taxInput.value);
    const purchaseDate = purchaseDateInput.value;

    if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(taxPct) || taxPct < 0 || taxPct >= 100) {
      yieldTd.textContent = "";
      taxedYieldTd.textContent = "";
      dirtyTd.textContent = "";
      taxEqTd.textContent = "";
      return;
    }

    yieldTd.textContent = "...";
    taxedYieldTd.textContent = "...";
    dirtyTd.textContent = "...";
    taxEqTd.textContent = "...";
    try {
      const resp = await fetch("/gilts/api/yield", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          isin: row.isin,
          price: price,
          tax_rate: taxPct / 100.0,
          purchase_date: purchaseDate,
        }),
      });
      const body = await resp.json();
      if (localSeq !== seq) return;
      if (!resp.ok) {
        yieldTd.textContent = "ERR";
        taxedYieldTd.textContent = "ERR";
        dirtyTd.textContent = "ERR";
        taxEqTd.textContent = body.error || "error";
        return;
      }
      yieldTd.textContent = toPct(body.annualized_yield);
      taxedYieldTd.textContent = toPct(body.post_tax_return);
      dirtyTd.textContent = fmtNum(body.dirty_price_per_100, 6);
      taxEqTd.textContent = toPct(body.gross_equivalent_yield);
    } catch (e) {
      if (localSeq !== seq) return;
      yieldTd.textContent = "ERR";
      taxedYieldTd.textContent = "ERR";
      dirtyTd.textContent = "ERR";
      taxEqTd.textContent = "network";
    }
  }

  priceInput.addEventListener("input", recalc);
  taxInput.addEventListener("input", recalc);
  purchaseDateInput.addEventListener("input", recalc);
  return tr;
}

async function load() {
  const meta = document.getElementById("meta");
  const currentTbody = document.querySelector("#gilts-table-current tbody");
  const pastTbody = document.querySelector("#gilts-table-past tbody");
  const pastTitle = document.getElementById("past-title");
  try {
    const resp = await fetch("/gilts/api/gilts");
    const body = await resp.json();
    if (!resp.ok) {
      meta.textContent = `Error: ${body.error || "failed to load gilts"}`;
      return;
    }
    const activeRows = body.active_rows || [];
    const pastRows = body.past_rows || [];
    meta.textContent = `Current: ${activeRows.length} | Past: ${pastRows.length}`;
    pastTitle.textContent = `Past Gilts (Redeemed Before ${body.today})`;
    for (const row of activeRows) {
      currentTbody.appendChild(buildRow(row));
    }
    for (const row of pastRows) {
      pastTbody.appendChild(buildRow(row));
    }
  } catch (e) {
    meta.textContent = "Error: network failure";
  }
}

load();
