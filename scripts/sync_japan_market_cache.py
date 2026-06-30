#!/usr/bin/env python3
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib import error, parse, request


JQUANTS_BASE_URL = "https://api.jquants.com/v2"
IMPORT_URL = os.environ.get(
    "CHICHANG_MARKET_IMPORT_URL",
    "https://chichangstockapp.com/api/market/cache/import",
)


def fetch_jquants(path, params=None):
    api_key = os.environ.get("JQUANTS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("JQUANTS_API_KEY is required")
    query = parse.urlencode({k: v for k, v in (params or {}).items() if v})
    url = f"{JQUANTS_BASE_URL}/{path}"
    if query:
        url = f"{url}?{query}"
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "QichangStockLedger-MarketSync/1.0",
            "x-api-key": api_key,
        },
    )
    for attempt in range(3):
        try:
            with request.urlopen(req, timeout=120) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"message": body}
            if exc.code == 429 and attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
            return exc.code, payload


def coverage_end_date(message):
    match = re.search(r"\d{4}-\d{2}-\d{2}\s*~\s*(\d{4}-\d{2}-\d{2})", message or "")
    return match.group(1) if match else None


def recent_dates(days=5):
    today = datetime.now(timezone.utc).date()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(days)]


def display_code(code):
    text = str(code or "").strip()
    return text[:4] if len(text) == 5 and text.endswith("0") and text[:4].isdigit() else text


def number_value(value):
    if value is None:
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
        return parsed if parsed == parsed else None
    except ValueError:
        return None


def first_text(row, names):
    for name in names:
        value = row.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def fetch_daily_quotes():
    force_date = os.environ.get("JQUANTS_FORCE_DATE", "").strip()
    if force_date:
        status, payload = fetch_jquants("equities/bars/daily", {"date": force_date})
        rows = payload.get("data") or []
        if status == 200 and len(rows) >= 1000:
            return force_date, rows
        raise RuntimeError(f"J-Quants forced date validation failed: status={status}, rows={len(rows)}")

    fallback_date = None
    tried = set()
    for date in recent_dates():
        tried.add(date)
        status, payload = fetch_jquants("equities/bars/daily", {"date": date})
        fallback_date = fallback_date or coverage_end_date(payload.get("message", ""))
        rows = payload.get("data") or []
        if status == 200 and len(rows) >= 1000:
            return date, rows
    if fallback_date and fallback_date not in tried:
        status, payload = fetch_jquants("equities/bars/daily", {"date": fallback_date})
        rows = payload.get("data") or []
        if status == 200 and len(rows) >= 1000:
            return fallback_date, rows
    status, payload = fetch_jquants("equities/bars/daily", {"date": "2026-04-07"})
    rows = payload.get("data") or []
    if status == 200 and len(rows) >= 1000:
        return "2026-04-07", rows
    raise RuntimeError(f"J-Quants daily quote validation failed: status={status}, rows={len(rows)}")


def build_records():
    status, payload = fetch_jquants("equities/master")
    master_rows = payload.get("data") or []
    if status != 200 or len(master_rows) < 1000:
        raise RuntimeError(f"J-Quants master validation failed: status={status}, rows={len(master_rows)}")

    as_of, quote_rows = fetch_daily_quotes()
    quote_by_code = {str(row.get("Code") or "").strip(): row for row in quote_rows}
    now = datetime.now(timezone.utc).isoformat()
    records = []
    for row in master_rows:
        code = str(row.get("Code") or "").strip()
        if not code:
            continue
        quote = quote_by_code.get(code)
        shown_code = display_code(code)
        price = number_value((quote or {}).get("AdjC") or (quote or {}).get("C"))
        volume = number_value((quote or {}).get("AdjVo") or (quote or {}).get("Vo"))
        records.append({
            "market": "japan",
            "code": shown_code,
            "displaySymbol": shown_code,
            "exchange": first_text(row, ["MktNm", "Mkt", "ProductCategory"]) or "JPX",
            "name": first_text(row, ["CoNameEn", "CompanyNameEnglish", "CoName", "CompanyName"]) or shown_code,
            "currency": "JPY",
            "price": price,
            "previousClose": None,
            "change": None,
            "changePercent": None,
            "volume": volume,
            "marketCap": None,
            "source": "J-Quants",
            "asOf": as_of,
            "updatedAt": now,
        })
    if len(records) < 1000:
        raise RuntimeError(f"Japan record validation failed: only {len(records)} records")
    return as_of, records


def upload(as_of, records):
    secret = os.environ.get("MARKET_SYNC_SECRET", "").strip()
    if not secret:
        raise RuntimeError("MARKET_SYNC_SECRET is required")
    payload = {
        "market": "japan",
        "source": "J-Quants",
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
    as_of, records = build_records()
    priced = sum(1 for record in records if record.get("price"))
    if priced < 1000:
        raise RuntimeError(f"Japan price validation failed: only {priced} priced records")
    print(f"Prepared {len(records)} Japan records ({priced} priced), asOf={as_of}")
    upload(as_of, records)


if __name__ == "__main__":
    main()
