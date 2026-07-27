#!/usr/bin/env python3
import unittest
from datetime import date

import sync_korea_market_cache as sync


class FakeFrame:
    def __init__(self, dates):
        self.index = dates
        self.empty = not dates


class KoreaMarketDateTests(unittest.TestCase):
    def test_weekend_run_uses_previous_trading_date(self):
        calls = []

        def reader(symbol, start):
            calls.append((symbol, start))
            return FakeFrame(["2026-07-23", "2026-07-24"])

        result = sync.latest_korea_trading_date(
            today=date(2026, 7, 26),
            data_reader=reader,
        )

        self.assertEqual(result, "2026-07-24")
        self.assertEqual(calls, [("KS11", "2026-07-12")])

    def test_future_market_date_is_rejected(self):
        def reader(_symbol, _start):
            return FakeFrame(["2026-07-27"])

        with self.assertRaisesRegex(RuntimeError, "future KRX market date"):
            sync.latest_korea_trading_date(
                today=date(2026, 7, 26),
                data_reader=reader,
            )


if __name__ == "__main__":
    unittest.main()
