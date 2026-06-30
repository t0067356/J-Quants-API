#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone
from urllib import error, request


IMPORT_URL = os.environ.get(
    "CHICHANG_MARKET_IMPORT_URL",
    "https://chichangstockapp.com/api/market/cache/import",
)

SOURCES = [
    {
        "url": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        "source": "TWSE OpenAPI",
        "min_records": 500,
    },
    {
        "url": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
        "source": "TPEx Mainboard OpenAPI",
        "min_records": 500,
    },
    {
        "url": "https://www.tpex.org.tw/openapi/v1/tpex_esb_latest_statistics",
        "source": "TPEx Emerging Stock OpenAPI",
        "min_records": 100,
    },
]


def first_value(row, names):
    for name in names:
        value = row.get(name)
        if value is None:
            continue
        text = str(value).strip().strip('"')
        if text and text not in ("--", "---"):
            return value
    return None


def number_value(value):
    if value is None:
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text in ("--", "---"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def taiwan_date(value):
    text = str(value or "").strip()
    if len(text) == 7 and text.isdigit():
        year = int(text[:3]) + 1911
        return f"{year:04d}-{text[3:5]}-{text[5:7]}"
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if "/" in text:
        parts = text.split("/")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            year = int(parts[0])
            if year < 1911:
                year += 1911
            return f"{year:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return text or datetime.now(timezone.utc).date().isoformat()


def fetch_json(url):
    req = request.Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 QichangStockLedger-MarketSync/1.0",
        },
    )
    with request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode("utf-8-sig")
    return json.loads(body)


def record_from_row(row, source, updated_at):
    code = first_value(row, ["Code", "SecuritiesCompanyCode", "代號", "證券代號", "有價證券代號"])
    name = first_value(row, ["Name", "CompanyName", "SecuritiesCompanyName", "有價證券名稱", "證券名稱", "公司名稱", "名稱"])
    if not code or not name:
        return None
    price = number_value(first_value(row, ["ClosingPrice", "Close", "收盤", "收盤價", "最後成交價", "成交價", "LatestPrice"]))
    change = number_value(first_value(row, ["Change", "漲跌價差", "漲跌"]))
    as_of = taiwan_date(first_value(row, ["Date", "日期"]))
    previous_close = price - change if price is not None and change is not None else None
    return {
        "market": "taiwan",
        "code": str(code).strip().upper(),
        "displaySymbol": str(code).strip().upper(),
        "exchange": source,
        "name": str(name).strip(),
        "currency": "TWD",
        "price": price,
        "previousClose": previous_close,
        "change": change,
        "source": source,
        "asOf": as_of,
        "updatedAt": updated_at,
    }


def build_records():
    updated_at = datetime.now(timezone.utc).isoformat()
    all_records = []
    for item in SOURCES:
        payload = fetch_json(item["url"])
        if not isinstance(payload, list):
            raise RuntimeError(f"{item['source']} did not return a JSON array")
        records = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            record = record_from_row(row, item["source"], updated_at)
            if record:
                records.append(record)
        if len(records) < item["min_records"]:
            raise RuntimeError(f"{item['source']} validation failed: only {len(records)} records")
        print(f"Prepared {len(records)} records from {item['source']}")
        all_records.extend(records)
    if len(all_records) < 1000:
        raise RuntimeError(f"Taiwan record validation failed: only {len(all_records)} records")
    return all_records


def upload(records):
    secret = os.environ.get("MARKET_SYNC_SECRET", "").strip()
    if not secret:
        raise RuntimeError("MARKET_SYNC_SECRET is required")
    as_of = max((record.get("asOf") or "" for record in records), default=datetime.now(timezone.utc).date().isoformat())
    payload = {
        "market": "taiwan",
        "source": "TWSE/TPEx OpenAPI",
        "asOf": as_of,
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
            print(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        raise


def main():
    records = build_records()
    print(f"Prepared {len(records)} Taiwan market records")
    upload(records)


if __name__ == "__main__":
    main()
