# Gilts Yield App

UK conventional gilt explorer and yield calculator with a small Python backend and a static frontend.

Browsable deployment: http://mazzo.li/gilts/

This project (including this file) is AI generated with human supervision.

## What this project does

- Loads DMO-style "Gilts in Issue" spreadsheet data from `./gilts/*.xls`.
- Extracts conventional gilts and exposes them over a JSON API.
- Computes:
  - Dirty price from clean price + accrued interest
  - Effective annual yield (XIRR-style)
  - Post tax return
  - Gross equivalent yield
- Serves a browser UI (when run with static serving enabled).

## Repository layout

- `gilt_yield.py`: data parsing + yield math.
- `gilts_webapp.py`: HTTP API server (and optional static file serving for development).
- `static/`: frontend (`index.html`, `app.js`, `styles.css`).
- `gilts/`: input spreadsheet files.

## Running the app

Start API + static UI:

```bash
python gilts_webapp.py --serve-static
```

Then open:

- `http://127.0.0.1:5001/gilts`

API-only mode:

```bash
python gilts_webapp.py
```

## API

### `GET /gilts/api/gilts`

Returns:

- `today`: server date (`YYYY-MM-DD`)
- `active_rows`: gilts with redemption date >= `today`
- `past_rows`: gilts with redemption date < `today`

### `POST /gilts/api/yield`

Request JSON:

- `isin`: string, e.g. `GB00...`
- `price`: clean price per 100 nominal
- `tax_rate`: decimal fraction, e.g. `0.40`
- `purchase_date` (optional): `YYYY-MM-DD`

Response JSON includes:

- `accrued_interest_per_100`
- `dirty_price_per_100`
- `annualized_yield`
- `post_tax_return`
- `gross_equivalent_yield`
- `is_ex_dividend_period`
- `next_coupon_date`

## Yield model used

The main yield field is an effective annual IRR-like number:

- Uses dated cashflows and solves discount rate `r` such that NPV is zero.
- Time exponent uses `days/365` (actual calendar day count divided by 365.0).
- Initial outflow is `-dirty_price`.
- Future inflows are coupon and redemption cashflows.

Taxed yield:

- Same solver and timing.
- Coupon component is reduced by `tax_rate`.
- Principal repayment is not taxed in the model.

Gross equivalent yield:

- `post_tax_return / (1 - tax_rate)`

## Important assumptions and imprecisions

These are deliberate current-model choices or known limitations.

### Convention differences from bond-market quoting

- This is not a GRY/DMO quote-convention calculator.
- It does not implement Act/Act ICMA + semiannual bond-equivalent quoting conventions.
- If you compare against quoted gilt yields from market data pages, small or sometimes meaningful differences are expected.

### Day count and compounding

- Uses effective annual IRR with `days/365`.
- Leap years are not modeled with a changing denominator (e.g. 366 in leap years).

### Coupon cashflow assumptions

- Coupon per period is modeled as `coupon_rate / 2`.
- Irregular first/long/short coupon stubs are not explicitly modeled.
- If a gilt has non-standard first coupon structure, yields may be off.

### Ex-dividend logic

- Ex-div period start is computed as 7 business days before next coupon.
- "Business day" currently means weekday only (Mon-Fri), not UK bank-holiday-aware.
- Around holiday periods, ex-div boundary classification can be off by a day.

### Tax modeling

- Single constant `tax_rate` is applied to coupon cashflows only.
- Capital gains are intentionally left untaxed to mirror UK gilt treatment; broader gains/losses, allowances, wrappers, and lot-level tax treatment are not modeled.
- This is a simplified comparison signal, not tax advice.

### Data ingestion assumptions

- Input is expected to be DMO-like `.xls` format and headers.
- Parser is strict on required columns in the conventional gilts section.
- Header/schema changes in source spreadsheets can cause hard failures.

### Scope assumptions

- Conventional gilts are parsed; index-linked section is not modeled for yield calc.
- Settlement defaults to workbook `Data Date` when no purchase date is provided.
- Merged dataset keeps the latest row per ISIN across local files.

## Possible surprises in behavior

- Same `isin` + `price` can return different yields if `purchase_date` changes, because accrued interest and ex-div inclusion change.
- Near ex-div boundary dates, `annualized_yield` can jump due to coupon inclusion/exclusion.
- `post_tax_return` can diverge more than expected at high tax rates and short maturities.
- Missing or malformed rows in the source workbook are skipped or can trigger parsing errors depending on where they occur.

## Security and operational notes

- API errors returned to clients are generic (`Invalid request` / `Internal server error`), while tracebacks are logged server-side.
- There is no authentication at the app layer.
- The built-in Python HTTP server is simple and intended for lightweight/self-hosted use, not high-throughput hostile traffic.

## Not investment advice

This project is for exploration and comparison tooling. It is not financial, tax, or investment advice.
