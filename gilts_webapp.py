#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import traceback
from typing import Any, Dict
from urllib.parse import urlparse

import gilt_yield


HOST = "127.0.0.1"
PORT = 5001
GILTS_DIR = (Path(__file__).resolve().parent / "gilts").resolve()
STATIC_ROOT = (Path(__file__).resolve().parent / "static").resolve()


def _json_default(x: Any) -> Any:
    if isinstance(x, date):
        return x.isoformat()
    raise TypeError(f"Cannot JSON serialize {type(x)}")


class Handler(BaseHTTPRequestHandler):
    server_version = "GiltsWebApp/1.0"
    serve_static = False

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        suffix = path.suffix.lower()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".ico": "image/x-icon",
        }.get(suffix, "application/octet-stream")

        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _safe_static_path(self, requested: str) -> Path:
        rel = requested.lstrip("/")
        if rel in {"", "index.html"}:
            return STATIC_ROOT / "index.html"
        path = (STATIC_ROOT / rel).resolve()
        if not str(path).startswith(str(STATIC_ROOT)):
            raise PermissionError("Path traversal denied")
        return path

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/gilts/api/gilts":
            try:
                _, active_rows, past_rows = gilt_yield.load_merged_gilt_table_rows(gilts_dir=str(GILTS_DIR))
            except Exception:
                print("Error handling GET /gilts/api/gilts", flush=True)
                traceback.print_exc()
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal server error"})
                return

            self._send_json(
                HTTPStatus.OK,
                {
                    "today": date.today(),
                    "active_rows": [asdict(r) for r in active_rows],
                    "past_rows": [asdict(r) for r in past_rows],
                },
            )
            return

        if self.serve_static:
            static_request = path
            if path == "/gilts":
                static_request = "/"
            elif path.startswith("/gilts/"):
                static_request = path[len("/gilts") :]

            try:
                file_path = self._safe_static_path(static_request)
            except PermissionError:
                self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                return
            self._send_file(file_path)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/gilts/api/yield":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            content_len = int(self.headers.get("Content-Length", "0"))
            if content_len <= 0 or content_len > 16_384:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(content_len).decode("utf-8"))
            isin = str(payload["isin"]).strip()
            price = float(payload["price"])
            tax_rate = float(payload["tax_rate"])
            purchase_date_raw = payload.get("purchase_date")
            settlement_date = None
            if purchase_date_raw:
                settlement_date = datetime.strptime(str(purchase_date_raw), "%Y-%m-%d").date()
            result = gilt_yield.calculate_gilt_yield(
                isin=isin,
                buy_price_per_100=price,
                tax_rate=tax_rate,
                gilts_dir=str(GILTS_DIR),
                settlement_date=settlement_date,
            )
        except Exception:
            print("Error handling POST /gilts/api/yield", flush=True)
            traceback.print_exc()
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request"})
            return

        self._send_json(
            HTTPStatus.OK,
            {
                "isin": result.isin,
                "accrued_interest_per_100": result.accrued_interest_per_100,
                "dirty_price_per_100": result.dirty_price_per_100,
                "total_future_cashflow_per_100": result.total_future_cashflow_per_100,
                "annualized_yield": result.annualized_yield,
                "post_tax_return": result.post_tax_return,
                "gross_equivalent_yield": result.gross_equivalent_yield,
                "is_ex_dividend_period": result.is_ex_dividend_period,
                "next_coupon_date": result.next_coupon_date,
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve-static", action="store_true", help="Serve ./static files for standalone development")
    args = parser.parse_args()

    if not GILTS_DIR.exists():
        raise SystemExit(f"Missing directory: {GILTS_DIR}")
    if args.serve_static and not STATIC_ROOT.exists():
        raise SystemExit(f"Missing static directory: {STATIC_ROOT}")

    Handler.serve_static = args.serve_static

    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    mode = "api+static" if args.serve_static else "api-only"
    print(f"Serving ({mode}) on http://{HOST}:{PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
