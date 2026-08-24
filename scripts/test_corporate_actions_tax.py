#!/usr/bin/env python3
"""回测引擎：配股除权折算、差别化股息税、T+1 无价跳过的无网络回归。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_valuation_strategy as bt
from fetch_a_share_dividends import adjust_for_ex_dividend


def make_lot(code: str, shares: float, buy_day: str, cost: float, stop: float) -> bt.Lot:
    lot = bt.Lot(code=code, entry_date=buy_day, entry_ratio=0.8, entry_value=10.0,
                 entry_band_low=9.0, entry_band_high=11.0, entry_upside=0.25)
    lot.shares, lot.avg_cost, lot.entry_stop, lot.entry_stop_ma = shares, cost, stop, 60
    lot.sublots.append([buy_day, shares, 0.0])
    return lot


class RightsIssueTest(unittest.TestCase):
    def test_exchange_reference_price_formula(self) -> None:
        # 10 配 3 @ 8 元，无分红送转：(P + 0.3×8) ÷ 1.3
        self.assertAlmostEqual(adjust_for_ex_dividend(20.0, 0.0, 0.0, 0.3, 8.0), (20.0 + 2.4) / 1.3)
        # 并存：(P − D + rr·rp) ÷ (1 + k + rr)
        self.assertAlmostEqual(adjust_for_ex_dividend(20.0, 0.5, 0.2, 0.1, 5.0), (20.0 - 0.5 + 0.5) / 1.3)

    def test_apply_corporate_actions_rights_full_subscription(self) -> None:
        pf = bt.Portfolio(cash=1000.0)
        pf.lots["X"] = make_lot("X", 1000.0, "2020-01-10", 20.0, 18.0)
        actions = {"X": {"2020-06-01": (0.5, 0.0, 0.3, 8.0)}}
        bt.apply_corporate_actions(pf, "2020-06-01", actions)
        lot = pf.lots["X"]
        self.assertAlmostEqual(lot.shares, 1300.0)                     # 全额认购 300 股
        self.assertAlmostEqual(pf.rights_paid, 2400.0)
        self.assertAlmostEqual(pf.cash, 1000.0 + 500.0 - 1000.0 - 500.0)   # 红利 500 入账、现金 1,500 付认购
        self.assertAlmostEqual(pf.debt, 900.0)                         # 认购款不足部分计融资
        self.assertAlmostEqual(lot.avg_cost, (20.0 - 0.5 + 2.4) / 1.3)
        self.assertAlmostEqual(lot.entry_stop, (18.0 - 0.5 + 2.4) / 1.3)
        self.assertEqual(len(lot.sublots), 2)
        self.assertAlmostEqual(lot.sublots[0][2], 500.0)               # 原批已收红利 500
        self.assertEqual(lot.sublots[1][0], "2020-06-01")

    def test_exright_affine_with_rights(self) -> None:
        days = ["2020-05-29", "2020-06-01"]
        scale, shift = bt.exright_affine(days, {"2020-06-01": (0.5, 0.2, 0.1, 5.0)})
        p_prev = 20.0
        self.assertAlmostEqual(scale[0] * p_prev + shift[0], (p_prev - 0.5 + 0.5) / 1.3)
        self.assertEqual((scale[1], shift[1]), (1.0, 0.0))

    def test_load_actions_merges_rights_rows(self) -> None:
        import csv, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=["security_code", "ex_dividend_date", "cash_per_share", "share_ratio",
                                                   "rights_ratio", "rights_price"])
                w.writeheader()
                w.writerow({"security_code": "X", "ex_dividend_date": "2020-06-01", "cash_per_share": "0.5", "share_ratio": "0.2",
                            "rights_ratio": "", "rights_price": ""})
                w.writerow({"security_code": "X", "ex_dividend_date": "2020-06-01", "cash_per_share": "0", "share_ratio": "0",
                            "rights_ratio": "0.1", "rights_price": "5"})
            old = bt.ACTIONS
            try:
                bt.ACTIONS = path
                for got, want in zip(bt.load_actions()["X"]["2020-06-01"], (0.5, 0.2, 0.1, 5.0)):
                    self.assertAlmostEqual(got, want)
                for got, want in zip(bt.load_actions(include_rights=False)["X"]["2020-06-01"], (0.5, 0.2, 0.0, 0.0)):
                    self.assertAlmostEqual(got, want)
            finally:
                bt.ACTIONS = old


class DividendTaxTest(unittest.TestCase):
    def setUp(self) -> None:
        bt.DIVIDEND_TAX_ON = True

    def tearDown(self) -> None:
        bt.DIVIDEND_TAX_ON = False

    def test_rate_buckets(self) -> None:
        self.assertEqual(bt.dividend_tax_rate("2020-01-31", "2020-02-29"), 0.20)   # ≤1 个月（月末对齐）
        self.assertEqual(bt.dividend_tax_rate("2020-01-15", "2020-02-16"), 0.10)   # 1 个月零 1 天
        self.assertEqual(bt.dividend_tax_rate("2020-01-15", "2021-01-15"), 0.10)   # 恰 1 年（含）
        self.assertEqual(bt.dividend_tax_rate("2020-01-15", "2021-01-16"), 0.0)

    def test_fifo_settlement_on_sale(self) -> None:
        pf = bt.Portfolio(cash=0.0)
        lot = make_lot("X", 1000.0, "2020-01-10", 20.0, 18.0)
        lot.sublots.append(["2020-05-20", 1000.0, 0.0])
        lot.shares = 2000.0
        pf.lots["X"] = lot
        bt.apply_corporate_actions(pf, "2020-06-01", {"X": {"2020-06-01": (0.5, 0.0, 0.0, 0.0)}})
        self.assertAlmostEqual(pf.cash, 1000.0)                        # 税前红利全额入账
        # 2020-06-10 卖 1500 股：先出 1 月批 1000 股（持有 5 个月 → 10% × 500）、再出 5 月批 500 股（≤1 个月 → 20% × 250）
        tax = bt.sell_dividend_tax(pf, lot, 1500.0, "2020-06-10")
        self.assertAlmostEqual(tax, 0.10 * 500.0 + 0.20 * 250.0)
        self.assertAlmostEqual(pf.dividend_tax_paid, tax)
        self.assertEqual(len(lot.sublots), 1)
        self.assertAlmostEqual(lot.sublots[0][1], 500.0)
        self.assertAlmostEqual(lot.sublots[0][2], 250.0)
        # 一年后卖出余下 500 股：免税
        self.assertAlmostEqual(bt.sell_dividend_tax(pf, lot, 500.0, "2021-07-01"), 0.0)

    def test_close_lot_settles_tax(self) -> None:
        pf = bt.Portfolio(cash=0.0)
        pf.lots["X"] = make_lot("X", 1000.0, "2020-01-10", 20.0, 18.0)
        bt.apply_corporate_actions(pf, "2020-06-01", {"X": {"2020-06-01": (1.0, 0.0, 0.0, 0.0)}})
        bt.FEES["paid"] = bt.FEES.get("paid", 0.0)
        bt.close_lot(pf, "X", "2020-06-15", 20.0, "test")
        self.assertAlmostEqual(pf.dividend_tax_paid, 100.0)            # 5 个月 → 10% × 1,000

    def test_switch_off_is_zero(self) -> None:
        bt.DIVIDEND_TAX_ON = False
        pf = bt.Portfolio(cash=0.0)
        lot = make_lot("X", 1000.0, "2020-01-10", 20.0, 18.0)
        lot.sublots[0][2] = 500.0
        self.assertEqual(bt.sell_dividend_tax(pf, lot, 1000.0, "2020-06-10"), 0.0)


if __name__ == "__main__":
    unittest.main()
