#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import Lock
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

import scipy.optimize
import xlrd


MONTH_BY_ABBR = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

UNICODE_FRACTIONS = {
    "¼": "1/4",
    "½": "1/2",
    "¾": "3/4",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}

MONTH_NAME_TO_NUM = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_MERGED_GILTS_CACHE_LOCK = Lock()
_MERGED_GILTS_CACHE: Dict[
    Tuple[str, Tuple[Tuple[str, int, int], ...]],
    Tuple[date, Dict[str, "Gilt"], List["GiltRow"]],
] = {}


@dataclass(frozen=True)
class Cashflow:
    payment_date: date
    amount_per_100: float


@dataclass(frozen=True)
class Gilt:
    name: str
    isin: str
    redemption_date: date
    first_issue_date: date
    coupon_rate_percent: float
    coupon_day: int
    coupon_months: Tuple[int, int]
    category: str

    @property
    def coupon_per_period_per_100(self) -> float:
        return self.coupon_rate_percent / 2.0


@dataclass(frozen=True)
class GiltRow:
    category: str
    name: str
    isin: str
    redemption_date: date
    first_issue_date: date
    dividend_dates: str
    total_amount_in_issue_million: Optional[float]
    coupon_rate_percent: float


@dataclass(frozen=True)
class GiltYieldResult:
    isin: str
    gilt_name: str
    settlement_date: date
    clean_price_per_100: float
    accrued_interest_per_100: float
    dirty_price_per_100: float
    annualized_yield: float
    post_tax_return: float
    gross_equivalent_yield: float
    tax_rate: float
    next_coupon_date: date
    previous_coupon_date: date
    is_ex_dividend_period: bool
    future_cashflows_per_100: Tuple[Cashflow, ...]
    total_future_cashflow_per_100: float


def _previous_business_day(d: date) -> date:
    while True:
        d = d - timedelta(days=1)
        if d.weekday() < 5:
            return d


def _subtract_business_days(d: date, n: int) -> date:
    out = d
    for _ in range(n):
        out = _previous_business_day(out)
    return out


def _parse_data_date_from_workbook_cell(value: str) -> date:
    m = re.search(r"\bData\s*Date\s*:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})\b", value)
    if not m:
        raise ValueError("Could not parse data date from workbook.")
    return datetime.strptime(m.group(1), "%d-%b-%Y").date()


def _normalize_header(header: str) -> str:
    return re.sub(r"\s+", " ", header).strip().lower()


def _find_latest_gilts_file(gilts_dir: str = "gilts") -> str:
    p = Path(gilts_dir)
    if not p.exists():
        raise FileNotFoundError(f"Gilts directory does not exist: {gilts_dir}")

    dated: List[Tuple[date, Path]] = []
    fallback: List[Path] = []
    for f in p.glob("*.xls"):
        if "Gilts in Issue" not in f.name:
            continue
        m = re.match(r"(\d{8}) - Gilts in Issue\.xls$", f.name)
        if m:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
            dated.append((d, f))
        else:
            fallback.append(f)

    if dated:
        return str(max(dated, key=lambda x: x[0])[1])
    if fallback:
        return str(max(fallback, key=lambda x: x.stat().st_mtime))
    raise FileNotFoundError(f"No gilt workbook found under {gilts_dir}")


def _list_gilts_files(gilts_dir: str = "gilts") -> List[str]:
    p = Path(gilts_dir)
    if not p.exists():
        raise FileNotFoundError(f"Gilts directory does not exist: {gilts_dir}")

    dated: List[Tuple[date, Path]] = []
    fallback: List[Path] = []
    for f in p.glob("*.xls"):
        if "Gilts in Issue" not in f.name:
            continue
        m = re.match(r"(\d{8}) - Gilts in Issue\.xls$", f.name)
        if m:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
            dated.append((d, f))
        else:
            fallback.append(f)

    dated_sorted = [str(x[1]) for x in sorted(dated, key=lambda x: x[0])]
    fallback_sorted = [str(x) for x in sorted(fallback, key=lambda x: x.stat().st_mtime)]
    files = dated_sorted + fallback_sorted
    if not files:
        raise FileNotFoundError(f"No gilt workbook found under {gilts_dir}")
    return files


def _to_date(value: object, datemode: int) -> date:
    if isinstance(value, float):
        y, m, d, _, _, _ = xlrd.xldate_as_tuple(value, datemode)
        return date(y, m, d)
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    raise TypeError(f"Unsupported date cell type: {type(value)}")


def _parse_coupon_rate_percent(name: str) -> float:
    if "%" not in name:
        raise ValueError(f"Cannot parse coupon rate from gilt name: {name}")

    prefix = name.split("%", 1)[0].strip()
    for uni, ascii_fraction in UNICODE_FRACTIONS.items():
        prefix = prefix.replace(uni, f" {ascii_fraction}")
    prefix = re.sub(r"\s+", " ", prefix).strip()

    if not prefix:
        raise ValueError(f"Cannot parse coupon rate from gilt name: {name}")

    total = 0.0
    for part in prefix.split(" "):
        if "/" in part:
            num, den = part.split("/", 1)
            total += float(num) / float(den)
        else:
            total += float(part)
    return total


def _parse_dividend_dates(dividend_dates: str) -> Tuple[int, Tuple[int, int]]:
    m = re.fullmatch(r"\s*(\d{1,2})\s+([A-Za-z]+)/([A-Za-z]+)\s*", dividend_dates)
    if not m:
        raise ValueError(f"Unrecognized dividend date format: {dividend_dates!r}")
    day = int(m.group(1))
    m1_name = m.group(2).strip().lower()
    m2_name = m.group(3).strip().lower()
    m1 = MONTH_BY_ABBR.get(m1_name[:3].title(), MONTH_NAME_TO_NUM.get(m1_name))
    m2 = MONTH_BY_ABBR.get(m2_name[:3].title(), MONTH_NAME_TO_NUM.get(m2_name))
    if m1 is None or m2 is None:
        raise ValueError(f"Unrecognized month names in dividend date format: {dividend_dates!r}")
    return day, tuple(sorted((m1, m2)))


def _coupon_schedule(gilt: Gilt) -> List[date]:
    dates: List[date] = []
    for y in range(gilt.first_issue_date.year - 1, gilt.redemption_date.year + 2):
        for m in gilt.coupon_months:
            try:
                d = date(y, m, gilt.coupon_day)
            except ValueError:
                continue
            if gilt.first_issue_date <= d <= gilt.redemption_date:
                dates.append(d)
    dates = sorted(set(dates))
    if gilt.redemption_date not in dates:
        dates.append(gilt.redemption_date)
        dates.sort()
    return dates


def _find_coupon_bounds(gilt: Gilt, settlement_date: date) -> Tuple[date, date]:
    schedule = _coupon_schedule(gilt)
    previous: Optional[date] = None
    nxt: Optional[date] = None
    for dt in schedule:
        if dt < settlement_date:
            previous = dt
            continue
        nxt = dt
        break
    if previous is None:
        previous = gilt.first_issue_date
    if nxt is None:
        raise ValueError(f"Settlement date {settlement_date} is after maturity for {gilt.isin}")
    return previous, nxt


def _future_cashflows(gilt: Gilt, settlement_date: date, include_next_coupon: bool) -> List[Cashflow]:
    schedule = _coupon_schedule(gilt)
    first_eligible = min((x for x in schedule if x >= settlement_date), default=None)
    cashflows: List[Cashflow] = []
    for dt in schedule:
        if dt < settlement_date:
            continue
        amount = 0.0
        if dt < gilt.redemption_date:
            amount += gilt.coupon_per_period_per_100
        elif dt == gilt.redemption_date:
            amount += gilt.coupon_per_period_per_100 + 100.0
        if dt == settlement_date and not include_next_coupon:
            continue
        if dt == first_eligible and not include_next_coupon:
            if dt == gilt.redemption_date:
                amount -= gilt.coupon_per_period_per_100
            else:
                amount = 0.0
        if amount > 0.0:
            cashflows.append(Cashflow(payment_date=dt, amount_per_100=amount))
    return cashflows


def xnpv(rate: float, values: List[Tuple[date, float]]) -> float:
    if rate <= -1.0:
        return float("inf")
    d0 = min([d for d, _ in values])
    return sum([vi / (1.0 + rate) ** ((di - d0).days / 365.0) for di, vi in values])


def xirr(values: List[Tuple[date, float]]) -> float:
    res: float
    try:
        res = scipy.optimize.newton(lambda r: xnpv(r, values), 0.0)
    except Exception:
        try:
            res = scipy.optimize.brentq(lambda r: xnpv(r, values), -0.999999999, 1e10)
        except Exception:
            res = float("nan")
    return res


def _gilts_files_signature(gilts_dir: str) -> Tuple[Tuple[str, int, int], ...]:
    entries: List[Tuple[str, int, int]] = []
    for path in _list_gilts_files(gilts_dir=gilts_dir):
        p = Path(path)
        st = p.stat()
        entries.append((str(p.resolve()), st.st_mtime_ns, st.st_size))
    return tuple(entries)


def load_gilts(gilts_xls_path: str) -> Tuple[date, Dict[str, Gilt], List[GiltRow]]:
    wb = xlrd.open_workbook(gilts_xls_path)
    sh = wb.sheet_by_index(0)

    data_date = _parse_data_date_from_workbook_cell(str(sh.cell_value(0, 0)))
    gilts: Dict[str, Gilt] = {}
    rows_out: List[GiltRow] = []
    current_category = ""
    in_conventional = False
    header_map: Dict[str, int] = {}

    def col(name: str) -> int:
        k = _normalize_header(name)
        if k not in header_map:
            raise ValueError(f"Missing required column '{name}' in worksheet header.")
        return header_map[k]

    for r in range(sh.nrows):
        row = [sh.cell_value(r, c) for c in range(sh.ncols)]
        row_text = [str(x).strip() for x in row]
        if not any(row_text):
            continue

        normalized = [_normalize_header(x) for x in row_text]
        if "conventional gilts" in normalized:
            in_conventional = True
        if any("index-linked gilts" in x for x in normalized):
            in_conventional = False
            continue
        if in_conventional and "isin code" in normalized and "redemption date" in normalized:
            header_map = {normalized[c]: c for c in range(sh.ncols) if normalized[c]}
            continue
        if not in_conventional or not header_map:
            continue

        name = str(row[0]).strip()
        if name in {"Ultra-Short", "Short", "Medium", "Long"}:
            current_category = name
            continue

        isin = str(row[col("ISIN Code")]).strip()
        if not re.fullmatch(r"[A-Z0-9]{12}", isin):
            continue

        redemption_date = _to_date(row[col("Redemption Date")], wb.datemode)
        first_issue_date = _to_date(row[col("First Issue Date")], wb.datemode)
        coupon_day, coupon_months = _parse_dividend_dates(str(row[col("Dividend Dates")]))
        coupon_rate_percent = _parse_coupon_rate_percent(name)
        total_amount_cell = row[col("Total Amount in Issue (£ million nominal)")]
        total_amount = float(total_amount_cell) if isinstance(total_amount_cell, float) else None

        gilts[isin] = Gilt(
            name=name,
            isin=isin,
            redemption_date=redemption_date,
            first_issue_date=first_issue_date,
            coupon_rate_percent=coupon_rate_percent,
            coupon_day=coupon_day,
            coupon_months=coupon_months,
            category=current_category,
        )
        rows_out.append(
            GiltRow(
                category=current_category,
                name=name,
                isin=isin,
                redemption_date=redemption_date,
                first_issue_date=first_issue_date,
                dividend_dates=str(row[col("Dividend Dates")]).strip(),
                total_amount_in_issue_million=total_amount,
                coupon_rate_percent=coupon_rate_percent,
            )
        )

    return data_date, gilts, rows_out


def load_gilt_table_rows(*, gilts_xls_path: Optional[str] = None, gilts_dir: str = "gilts") -> Tuple[date, List[GiltRow]]:
    gilts_file = gilts_xls_path or _find_latest_gilts_file(gilts_dir=gilts_dir)
    data_date, _, rows = load_gilts(gilts_file)
    return data_date, rows


def load_merged_gilts(
    *,
    gilts_xls_path: Optional[str] = None,
    gilts_dir: str = "gilts",
) -> Tuple[date, Dict[str, Gilt], List[GiltRow]]:
    if gilts_xls_path is not None:
        return load_gilts(gilts_xls_path)

    signature = _gilts_files_signature(gilts_dir=gilts_dir)
    cache_key = (str(Path(gilts_dir).resolve()), signature)
    with _MERGED_GILTS_CACHE_LOCK:
        cached = _MERGED_GILTS_CACHE.get(cache_key)
    if cached is not None:
        data_date, gilts, rows = cached
        return data_date, dict(gilts), list(rows)

    merged: Dict[str, Tuple[date, Gilt, GiltRow]] = {}
    newest_data_date: Optional[date] = None
    for f, _, _ in signature:
        data_date, gilts, rows = load_gilts(f)
        if newest_data_date is None or data_date > newest_data_date:
            newest_data_date = data_date
        row_by_isin = {r.isin: r for r in rows}
        for isin, g in gilts.items():
            existing = merged.get(isin)
            row = row_by_isin[isin]
            if existing is None or data_date > existing[0]:
                merged[isin] = (data_date, g, row)

    if newest_data_date is None:
        raise FileNotFoundError(f"No parsable gilt workbook found under {gilts_dir}")

    merged_gilts = {isin: x[1] for isin, x in merged.items()}
    merged_rows = [x[2] for x in merged.values()]
    merged_rows.sort(key=lambda r: (r.redemption_date, r.name))
    with _MERGED_GILTS_CACHE_LOCK:
        _MERGED_GILTS_CACHE[cache_key] = (newest_data_date, dict(merged_gilts), list(merged_rows))
    return newest_data_date, merged_gilts, merged_rows


def load_merged_gilt_table_rows(
    *,
    gilts_xls_path: Optional[str] = None,
    gilts_dir: str = "gilts",
) -> Tuple[date, List[GiltRow], List[GiltRow]]:
    data_date, _, rows = load_merged_gilts(gilts_xls_path=gilts_xls_path, gilts_dir=gilts_dir)
    today = date.today()
    active = [r for r in rows if r.redemption_date >= today]
    past = [r for r in rows if r.redemption_date < today]
    active.sort(key=lambda r: (r.redemption_date, r.name))
    past.sort(key=lambda r: (r.redemption_date, r.name))
    return data_date, active, past


def calculate_gilt_yield(
    *,
    isin: str,
    buy_price_per_100: float,
    gilts_xls_path: Optional[str] = None,
    gilts_dir: str = "gilts",
    tax_rate: float,
    settlement_date: Optional[date] = None,
) -> GiltYieldResult:
    """
    Calculates current annualized yield for a conventional gilt and gross equivalent yield.

    buy_price_per_100 is assumed to be a clean price.
    tax_rate is a decimal fraction (e.g. 0.40 for 40% tax).
    """
    if not (0.0 <= tax_rate < 1.0):
        raise ValueError("tax_rate must be in [0.0, 1.0).")
    if buy_price_per_100 <= 0.0:
        raise ValueError("buy_price_per_100 must be positive.")

    data_date, gilts, _ = load_merged_gilts(gilts_xls_path=gilts_xls_path, gilts_dir=gilts_dir)
    gilt = gilts.get(isin)
    if gilt is None:
        raise KeyError(f"ISIN not found in conventional gilts: {isin}")

    settlement = settlement_date or data_date
    prev_coupon, next_coupon = _find_coupon_bounds(gilt, settlement)
    period_days = (next_coupon - prev_coupon).days
    elapsed_days = (settlement - prev_coupon).days
    if period_days <= 0:
        raise ValueError("Invalid coupon period.")

    coupon = gilt.coupon_per_period_per_100
    accrued = coupon * (elapsed_days / period_days)
    ex_div_start = _subtract_business_days(next_coupon, 7)
    is_ex_div = ex_div_start <= settlement < next_coupon
    if is_ex_div:
        accrued -= coupon

    dirty = buy_price_per_100 + accrued
    future_cashflows = _future_cashflows(
        gilt=gilt,
        settlement_date=settlement,
        include_next_coupon=not is_ex_div,
    )
    irr_inputs: List[Tuple[date, float]] = [(settlement, -dirty)] + [
        (cf.payment_date, cf.amount_per_100) for cf in future_cashflows
    ]
    annualized_yield = xirr(irr_inputs)

    taxed_irr_inputs: List[Tuple[date, float]] = [(settlement, -dirty)]
    for cf in future_cashflows:
        coupon_component = coupon if cf.payment_date < gilt.redemption_date else max(0.0, cf.amount_per_100 - 100.0)
        taxed_amount = cf.amount_per_100 - (coupon_component * tax_rate)
        taxed_irr_inputs.append((cf.payment_date, taxed_amount))
    post_tax_return = xirr(taxed_irr_inputs)

    gross_equivalent = post_tax_return / (1.0 - tax_rate)
    total_future_cashflow = sum(cf.amount_per_100 for cf in future_cashflows)

    return GiltYieldResult(
        isin=isin,
        gilt_name=gilt.name,
        settlement_date=settlement,
        clean_price_per_100=buy_price_per_100,
        accrued_interest_per_100=accrued,
        dirty_price_per_100=dirty,
        annualized_yield=annualized_yield,
        post_tax_return=post_tax_return,
        gross_equivalent_yield=gross_equivalent,
        tax_rate=tax_rate,
        next_coupon_date=next_coupon,
        previous_coupon_date=prev_coupon,
        is_ex_dividend_period=is_ex_div,
        future_cashflows_per_100=tuple(future_cashflows),
        total_future_cashflow_per_100=total_future_cashflow,
    )


def equivalent_pre_tax_yield(target_after_tax_yield: float, tax_rate: float) -> float:
    if not (0.0 <= tax_rate < 1.0):
        raise ValueError("tax_rate must be in [0.0, 1.0).")
    return target_after_tax_yield / (1.0 - tax_rate)
