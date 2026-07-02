#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib import error, request


IMPORT_URL = os.environ.get(
    "CHICHANG_MARKET_IMPORT_URL",
    "https://chichangstockapp.com/api/market/cache/import",
)
CACHE_URL = os.environ.get(
    "CHICHANG_MARKET_CACHE_URL",
    "https://chichangstockapp.com/api/market/cache?market=taiwan",
)
MAX_FETCH_ATTEMPTS = 3

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


def fetch_json(url, label):
    req = request.Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 QichangStockLedger-MarketSync/1.0",
        },
    )
    last_error = None
    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            with request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8-sig")
            return json.loads(body)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:240]
            last_error = RuntimeError(f"HTTP {exc.code}: {body or exc.reason or 'no response body'}")
            if exc.code not in (429, 500, 502, 503, 504, 520, 522, 524) or attempt >= MAX_FETCH_ATTEMPTS:
                break
        except Exception as exc:
            last_error = exc
            if attempt >= MAX_FETCH_ATTEMPTS:
                break
        delay = 10 * attempt
        print(f"{label} fetch failed on attempt {attempt}/{MAX_FETCH_ATTEMPTS}: {last_error}; retrying in {delay}s")
        time.sleep(delay)
    raise RuntimeError(f"{label} fetch failed after {MAX_FETCH_ATTEMPTS} attempts: {last_error}")


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


def source_matches(record_source, source):
    record = str(record_source or "").lower()
    target = source.lower()
    if "tpex" in target:
        return "tpex" in record
    if "twse" in target:
        return "twse" in record
    return record == target


def load_old_cache_records():
    try:
        payload = fetch_json(CACHE_URL, "Existing Taiwan cache")
    except Exception as exc:
        print(f"Existing Taiwan cache could not be loaded: {exc}", file=sys.stderr)
        return []
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        print("Existing Taiwan cache response did not include records", file=sys.stderr)
        return []
    print(f"Loaded {len(records)} existing Taiwan cache records for fallback")
    return [record for record in records if isinstance(record, dict)]


def build_records():
    updated_at = datetime.now(timezone.utc).isoformat()
    all_records = []
    failed_sources = []
    for item in SOURCES:
        try:
            payload = fetch_json(item["url"], item["source"])
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
        except Exception as exc:
            failed_sources.append({"source": item["source"], "reason": str(exc)})
            print(f"{item['source']} failed: {exc}", file=sys.stderr)

    if failed_sources:
        old_records = load_old_cache_records()
        for failure in failed_sources:
            fallback_records = [
                record for record in old_records
                if source_matches(record.get("source"), failure["source"])
            ]
            if not fallback_records:
                raise RuntimeError(
                    f"{failure['source']} failed and no old cache fallback was available: {failure['reason']}"
                )
            print(f"Using {len(fallback_records)} old records for {failure['source']} fallback")
            all_records.extend(fallback_records)
    if len(all_records) < 1000:
        raise RuntimeError(f"Taiwan record validation failed: only {len(all_records)} records")
    return all_records, failed_sources


def upload(records, failed_sources):
    secret = os.environ.get("MARKET_SYNC_SECRET", "").strip()
    if not secret:
        raise RuntimeError("MARKET_SYNC_SECRET is required")
    as_of = max((record.get("asOf") or "" for record in records), default=datetime.now(timezone.utc).date().isoformat())
    payload = {
        "market": "taiwan",
        "source": "TWSE/TPEx OpenAPI",
        "asOf": as_of,
        "status": "partial" if failed_sources else "ready",
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
    records, failed_sources = build_records()
    status = "partial" if failed_sources else "ready"
    if failed_sources:
        for failure in failed_sources:
            print(f"Partial Taiwan cache: {failure['source']} used fallback because {failure['reason']}")
    print(f"Prepared {len(records)} Taiwan market records, status={status}")
    upload(records, failed_sources)


if __name__ == "__main__":
    main()
