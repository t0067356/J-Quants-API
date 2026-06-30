#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone
from urllib import request, error

import FinanceDataReader as fdr


IMPORT_URL = os.environ.get(
    "CHICHANG_MARKET_IMPORT_URL",
    "https://chichangstockapp.com/api/market/cache/import",
)


def first_value(row, names):
    for name in names:
        if name in row and row[name] is not None:
            value = row[name]
            if str(value).strip() and str(value).strip().lower() != "nan":
                return value
    return None


def number_value(value):
    if value is None:
        return None
    try:
        parsed = float(str(value).replace(",", "").replace("%", "").strip())
        return parsed if parsed == parsed else None
    except ValueError:
        return None


def text_value(value):
    if value is None:
        return ""
    return str(value).strip()


def build_records():
    df = fdr.StockListing("KRX")
    if df is None or df.empty:
        raise RuntimeError("FinanceDataReader returned no KRX rows")

    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    records = []
    for _, series in df.iterrows():
        row = series.to_dict()
        code = text_value(first_value(row, ["Code", "Symbol", "Ticker", "종목코드"]))
        name = text_value(first_value(row, ["Name", "NameEng", "회사명", "종목명"]))
        if not code or not name:
            continue
        market = text_value(first_value(row, ["Market", "MarketId", "시장구분"])) or "KRX"
        price = number_value(first_value(row, ["Close", "Price", "현재가", "종가"]))
        previous_close = number_value(first_value(row, ["Open", "PrevClose", "기준가"]))
        change = number_value(first_value(row, ["Changes", "Change", "대비"]))
        change_percent = number_value(first_value(row, ["ChagesRatio", "ChangeRatio", "ChangePercent", "등락률"]))
        volume = number_value(first_value(row, ["Volume", "거래량"]))
        market_cap = number_value(first_value(row, ["Marcap", "MarketCap", "시가총액"]))
        records.append({
            "market": "korea",
            "code": code.zfill(6) if code.isdigit() else code,
            "displaySymbol": code.zfill(6) if code.isdigit() else code,
            "exchange": market,
            "name": name,
            "currency": "KRW",
            "price": price,
            "previousClose": previous_close,
            "change": change,
            "changePercent": change_percent,
            "volume": volume,
            "marketCap": market_cap,
            "source": "FinanceDataReader/KRX",
            "asOf": today,
            "updatedAt": now,
        })

    if len(records) < 500:
        raise RuntimeError(f"KRX record validation failed: only {len(records)} records")
    return records


def upload(records):
    secret = os.environ.get("MARKET_SYNC_SECRET", "").strip()
    if not secret:
        raise RuntimeError("MARKET_SYNC_SECRET is required")
    payload = {
        "market": "korea",
        "source": "FinanceDataReader/KRX",
        "asOf": datetime.now(timezone.utc).date().isoformat(),
        "records": records,
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
            "User-Agent": "QichangStockLedger-MarketSync/1.0",
        },
    )
    try:
        with request.urlopen(req, timeout=120) as resp:
            response_body = resp.read().decode("utf-8")
            print(response_body)
    except error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        raise


def main():
    records = build_records()
    print(f"Prepared {len(records)} KRX records")
    upload(records)


if __name__ == "__main__":
    main()
