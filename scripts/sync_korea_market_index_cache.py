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


def number_value(value):
    if value is None:
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
        return parsed if parsed == parsed else None
    except ValueError:
        return None


def build_points():
    start = (datetime.now(timezone.utc).date() - timedelta(days=14)).isoformat()
    df = fdr.DataReader("KS11", start)
    if df is None or df.empty:
        raise RuntimeError("FinanceDataReader returned no KOSPI rows")

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
            "source": "FinanceDataReader/KOSPI",
        })
    if not points:
        raise RuntimeError("FinanceDataReader returned no valid KOSPI close")
    return points[-5:]


def upload(points):
    secret = os.environ.get("MARKET_SYNC_SECRET", "").strip()
    if not secret:
        raise RuntimeError("MARKET_SYNC_SECRET is required")
    payload = {
        "index": "kospi",
        "source": "FinanceDataReader/KOSPI",
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
            "User-Agent": "QichangStockLedger-MarketIndexSync/1.0",
        },
    )
    try:
        with request.urlopen(req, timeout=120) as resp:
            print(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        raise


def main():
    points = build_points()
    print(f"Prepared {len(points)} KOSPI index points, latest={points[-1]['date']}")
    upload(points)


if __name__ == "__main__":
    main()
