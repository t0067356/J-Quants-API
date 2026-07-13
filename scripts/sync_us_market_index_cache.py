#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib import error, request

import FinanceDataReader as fdr


IMPORT_URL = os.environ.get(
    "CHICHANG_MARKET_INDEX_IMPORT_URL",
    "https://chichangstockapp.com/api/market/index/cache/import",
)
MARKET_INDEX_LOOKBACK_DAYS = 45

US_INDEXES = [
    ("sp500", "US500", "FinanceDataReader/S&P 500"),
    ("dowJones", "DJI", "FinanceDataReader/Dow Jones"),
    ("nasdaqComposite", "IXIC", "FinanceDataReader/Nasdaq Composite"),
    ("russell2000", "RUT", "FinanceDataReader/Russell 2000"),
]


def number_value(value):
    if value is None:
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
        return parsed if parsed == parsed else None
    except ValueError:
        return None


def build_points(symbol, source):
    start = (datetime.now(timezone.utc).date() - timedelta(days=MARKET_INDEX_LOOKBACK_DAYS)).isoformat()
    df = fdr.DataReader(symbol, start)
    if df is None or df.empty:
        raise RuntimeError(f"FinanceDataReader returned no rows for {symbol}")

    points = []
    for index, series in df.iterrows():
        row = series.to_dict()
        close = number_value(row.get("Close"))
        if not close:
            continue
        date_text = index.date().isoformat() if hasattr(index, "date") else str(index)[:10]
        points.append({
            "date": date_text,
            "close": close,
            "source": source,
        })
    if not points:
        raise RuntimeError(f"FinanceDataReader returned no valid close for {symbol}")
    return points[-5:]


def upload(index_code, source, points):
    secret = os.environ.get("MARKET_SYNC_SECRET", "").strip()
    if not secret:
        raise RuntimeError("MARKET_SYNC_SECRET is required")
    payload = {
        "index": index_code,
        "source": source,
        "asOf": points[-1]["date"],
        "points": points,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        IMPORT_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "QichangStockLedger-USMarketIndexSync/1.0",
        },
    )
    try:
        with request.urlopen(req, timeout=120) as resp:
            print(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        raise


def main():
    for index_code, symbol, source in US_INDEXES:
        points = build_points(symbol, source)
        print(f"Prepared {len(points)} {index_code} points from {symbol}, latest={points[-1]['date']}")
        upload(index_code, source, points)


if __name__ == "__main__":
    main()
