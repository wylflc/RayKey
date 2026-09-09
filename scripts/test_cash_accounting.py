"""OI-169／OI-170（工作流 §12.1 第 2 款「资金记账」）：新仓首日按成交日收盘盯市；买入含费税不得留下未融资的负现金；
同日对冲退回卖出款先在授信内融回；summary 报最低现金与负现金日数。"""
import math
import unittest
from pathlib import Path

import backtest_valuation_strategy as bt
from test_buy_top_pct import fixture, row

USER_FEES = {"commission": .0001, "min_fee": 5., "stamp": .0005, "transfer": .00001, "stamp_mode": "flat", "paid": 0.}


class CashAccountingTest(unittest.TestCase):
    def setUp(self):
        self.fees = dict(bt.FEES)
        self.tax = bt.DIVIDEND_TAX_ON
        bt.DIVIDEND_TAX_ON = False
        bt.FEES.update({"commission": 0., "min_fee": 0., "stamp": 0., "transfer": 0., "stamp_mode": "flat", "paid": 0.})
        self.addCleanup(lambda: (bt.FEES.clear(), bt.FEES.update(self.fees), setattr(bt, "DIVIDEND_TAX_ON", self.tax)))

    def test_new_position_is_marked_at_execution_close(self):
        # OI-169 复现：信号日收盘 10、成交日收盘 20，10 万元买 5% 一档 → 250 股；首日净值应为 100,000（此前记 97,500）
        days = {"2024-01-02": [row("A", .8, 10.)], "2024-01-03": [row("A", .8, 20.)], "2024-01-04": [row("A", .8, 20.)]}
        res, ledger = fixture(days)
        self.assertEqual([(r["date"], r["shares"], r["price"]) for r in ledger if r["action"] == "买入"][0],
                         ("2024-01-03", "250", "20.000"))
        first = next(r for r in res["equity"] if r[0] == "2024-01-03")
        self.assertAlmostEqual(first[1], 100_000.0, places=6)
        self.assertAlmostEqual(first[2], 95_000.0, places=6)

    def test_buy_fees_never_leave_unfunded_negative_cash(self):
        # OI-170 复现：10 万元现金、无授信，整仓买入 10 元股票；此前记现金 −11 元、负债 0
        bt.FEES.update(USER_FEES)
        days = {d: [row("A", .8, 10.)] for d in ("2024-01-02", "2024-01-03", "2024-01-04")}
        for lot_size, want_shares in ((0, None), (100, 9900)):
            res, ledger = fixture(days, x=1.0, lot_size=lot_size)
            self.assertEqual(sum(1 for r in ledger if r["action"] == "买入"), 1)
            invested = sum(l.invested for l in res["closed"])          # 截止清算后周期在 closed 里；流水股数四舍五入不可用
            fee = bt.quote_fee(invested, "2024-01-03", "buy")
            self.assertLessEqual(invested + fee, 100_000. + 1e-6)
            self.assertGreaterEqual(res["min_cash"], -1e-6)
            self.assertEqual(res["negative_cash_days"], 0)
            if want_shares:
                self.assertEqual(invested, want_shares * 10.)
            else:
                self.assertGreater(invested, 99_900.)                  # 无整手：只留出费用，不多留
        summary = bt.summarize("t", res, 100_000., {}, [])
        self.assertEqual(summary["负现金日数"], 0)
        self.assertGreaterEqual(summary["最低现金"], -1e-6)
        self.assertEqual(summary["最低现金日"], res["min_cash_day"])

    def test_affordable_amount_and_shares(self):
        bt.FEES.update(USER_FEES)
        day = "2024-01-03"
        for power in (100., 1_000., 100_000., 5_000_000.):
            a = bt.affordable_amount(power, day)
            self.assertLessEqual(a + bt._fee_quiet(a, day, "buy"), power + 1e-9)
            self.assertGreater(a + bt._fee_quiet(a, day, "buy"), power - 0.01)   # 不多留
        self.assertEqual(bt.affordable_amount(0., day), 0.)
        p = bt.Portfolio(cash=10_000.)
        self.assertEqual(bt.affordable_shares(p, 1_000., 10., day, 100, 0.), 900.)      # 1000 股含费超 1 万 → 缩一手
        p.cash = 9_505.
        self.assertEqual(bt.affordable_shares(p, 950., 10., day, 100, 0.), 850.)        # 对冲后的非整手净额（9,505.1 > 9,505）：步长仍一手
        p.cash = 10_000.
        self.assertEqual(bt.affordable_shares(p, 1_000., 10., day, 100, 5_000.), 1_000.)  # 授信内可融
        self.assertEqual(bt.affordable_shares(bt.Portfolio(cash=5.), 100., 10., day, 100, 0.), 0.)

    def _sale(self):
        lot = bt.Lot(code="A", entry_date="2024-01-02", entry_ratio=.8, entry_value=12.5, entry_band_low=10.,
                     entry_band_high=15., entry_upside=.25, shares=0., invested=1_000., proceeds=1_000., avg_cost=10.)
        reg = {}
        bt.register_sale(reg, "A", lot, 100., 10., consumed=[], whole=True, closed_idx=None, ledger_idx=None)
        return lot, reg

    def test_net_off_sale_refinances_within_credit_or_declines(self):
        # 卖出款 1,000 已用于偿还超额负债：授信无余量 → 不对冲、现金不为负；授信有余量 → 融回 1,000 再对冲
        lot, reg = self._sale()
        p = bt.Portfolio(cash=0., debt=1_000.)
        self.assertEqual(bt.net_off_sale(reg, p, "A", 100., "2024-01-03", None, limit=1_000.), (0., 0.))
        self.assertEqual((p.cash, p.debt, lot.shares), (0., 1_000., 0.))
        self.assertNotIn("A", p.lots)
        lot, reg = self._sale()
        p = bt.Portfolio(cash=0., debt=1_000.)
        netted, turn = bt.net_off_sale(reg, p, "A", 100., "2024-01-03", None, limit=2_000.)
        self.assertEqual((netted, turn), (100., -1_000.))
        self.assertAlmostEqual(p.cash, 0.)
        self.assertAlmostEqual(p.debt, 2_000.)
        self.assertEqual((lot.shares, "A" in p.lots), (100., True))
        # 部分可融：只对冲付得起的股数
        lot, reg = self._sale()
        p = bt.Portfolio(cash=0., debt=1_000.)
        netted, _ = bt.net_off_sale(reg, p, "A", 100., "2024-01-03", None, limit=1_400.)
        self.assertEqual(netted, 40.)
        self.assertGreaterEqual(p.cash, -1e-9)

    def test_leveraged_multi_day_path_has_no_negative_cash(self):
        bt.FEES.update(USER_FEES)
        px = {"A": [10., 10.5, 11., 7., 7.2, 7.5, 8., 9.5, 10., 10.5],
              "B": [20., 20.5, 21., 21.5, 14., 14.5, 15., 16., 17., 18.]}
        dates = [f"2024-01-{d:02d}" for d in (2, 3, 4, 5, 8, 9, 10, 11, 12, 15)]
        days = {d: [row("A", .8, px["A"][i]), row("B", .7, px["B"][i])] for i, d in enumerate(dates)}
        res, ledger = fixture(days, x=.5, lot_size=100, credit_ratio=.666, credit_cap=1e12, margin_rate=.035,
                              net_same_day=True, swap=True, swap_partial=True, gain_sell=1.05, gain_sell_mode="ungated")
        self.assertTrue(any(r["action"] == "买入" for r in ledger))
        self.assertGreaterEqual(res["min_cash"], -1e-6)
        self.assertEqual(res["negative_cash_days"], 0)
        self.assertGreater(max(r[4] for r in res["equity"]), 0.)     # 路径确实动用了授信

    def test_workflow_states_the_cash_accounting_rule(self):
        text = (Path(__file__).resolve().parents[1] / "docs/000_Ashare_workflow.md").read_text(encoding="utf-8")
        self.assertIn("**资金记账**：日末盯市对当日新建仓取成交日收盘", text)
        self.assertIn("同日对冲退回卖出款前先在授信内融回", text)
        import sweep_backtest_configs as sweep
        for key in ("最低现金", "负现金日数", "最低现金日"):
            self.assertIn(key, sweep.FIELDS)


if __name__ == "__main__":
    unittest.main()
