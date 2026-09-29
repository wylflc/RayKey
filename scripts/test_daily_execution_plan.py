#!/usr/bin/env python3
"""§9.3.2 执行清单（先卖后买）与 §9.3.3 冷却计数器的无网络回归。"""

from __future__ import annotations

import csv
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import screen_daily_volume_price_signals as scan


def row(code: str, name: str, close: float, ma20: float, ma60: float, pv: float | None,
        amount_ma20: float = 1e8, ma5: float | None = None, bt_stable: bool = True) -> dict:
    # v4.222 新建仓走势：近 3 日未创 20 日新低（bt_stable）且收盘 > MA5、> MA20；缺省 MA5 略低于收盘、已走稳
    r = {"security_code": code, "security_name": name, "close": close, "ma20": ma20, "ma60": ma60,
         "ma5": close * 0.99 if ma5 is None else ma5, "bt_stable": bt_stable,
         "amount_ma20": amount_ma20, "model_intrinsic_value": (close / pv) if pv else "",
         "model_band_source": "模型带", "quality_tier": "L2"}
    if pv is not None:
        r["model_pv"] = pv
        r["hold_pv"] = pv
    return r


def hold(name: str, shares: float, cost: float | None, stop: float | None) -> dict:
    return {"name": name, "shares": shares, "cost": cost, "stop": stop}


class ExecutionPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        scan.CLOSE_SERIES.clear()      # 无K线序列 → 相关性未知 → 放行（OI-093 语义）
        self.nav = 3_000_000.0        # 一档 15 万

    def run_plan(self, rows, holdings, funds, members=None, counters=None, holding_rows=None, sell_counters=None, **kw):
        return scan.section93_execution_plan(rows, self.nav, funds, holdings, set(), set(),
                                             members, counters if counters is not None else {}, holding_rows,
                                             sell_counters=sell_counters, **kw)

    def test_equity_bond_cap_forces_proportional_sells(self) -> None:
        # §9.3.1 股债总仓位上限（v4.176）：净资产 200 万，持仓 A 200 万 + B 100 万 = 150%；上限 100% → 超 100 万，按市值比例 1/3
        # 减仓、按手向上取整（A 6,700 股、B 6,700 股）；预算 = 现金 0 − 负债 100 万 = −100 万，卖出款 100.5 万先补缺口
        self.nav = 2_000_000.0
        rows = [row("000001", "A", close=100.0, ma20=101.0, ma60=90.0, pv=2.5),
                row("000002", "B", close=50.0, ma20=51.0, ma60=40.0, pv=2.5)]
        holdings = {"000001": hold("A", 20000, None, None), "000002": hold("B", 20000, None, None)}
        res = self.run_plan(rows, holdings, funds=0.0, members={"000001", "000002"}, exposure_cap=1.0, cap_cash=-1_000_000.0)
        sells = {s["security_code"]: s for s in res["sells"] if s["rule"] == "股债·总仓位上限"}
        self.assertEqual({c: s["sell_shares"] for c, s in sells.items()}, {"000001": 6700, "000002": 6700})
        self.assertEqual(res["eb_sells"], ["000001", "000002"])
        self.assertAlmostEqual(res["funds0"], -1_000_000.0)
        self.assertAlmostEqual(res["cash"], -1_000_000.0 + 6700 * 100 + 6700 * 50)
        self.assertAlmostEqual(res["eb_stock_before"], 3_000_000.0)
        self.assertAlmostEqual(res["eb_stock_after"], 3_000_000.0 - 670_000 - 335_000)
        # 未触发（exposure_cap=None）：同一输入没有减仓行，预算仍取 funds
        res = self.run_plan(rows, holdings_copy := {"000001": hold("A", 20000, None, None), "000002": hold("B", 20000, None, None)},
                            funds=0.0, members={"000001", "000002"})
        self.assertFalse([s for s in res["sells"] if s["rule"] == "股债·总仓位上限"]); self.assertIsNone(res["exposure_cap"])

    def test_equity_bond_cap_limits_buys_to_room(self) -> None:
        # 净资产 105 万、持仓 100 万、上限 100% → 余量 5 万；一档 5.25 万 → 只买 500 股；第二只候选余量 0 被挡下
        self.nav = 1_050_000.0
        rows = [row("000001", "A", close=100.0, ma20=101.0, ma60=90.0, pv=2.5),
                row("000003", "C", close=100.0, ma20=95.0, ma60=90.0, pv=0.5),
                row("000004", "D", close=100.0, ma20=95.0, ma60=90.0, pv=0.6)]
        holdings = {"000001": hold("A", 10000, None, None)}
        res = self.run_plan(rows, holdings, funds=1_000_000.0, members={"000001", "000003", "000004"}, exposure_cap=1.0, cap_cash=1_000_000.0)
        self.assertEqual([(p["security_code"], p["shares"]) for p in res["plan"]], [("000003", 500)])
        self.assertEqual([c["security_code"] for c in res["eb_capped"]], ["000004"])
        self.assertAlmostEqual(res["eb_stock_after"], 1_050_000.0)
        # 无上限时同一输入买满一档 500 股 → 1500 股？一档 5.25 万 ÷ 100 元 = 525 股 → 500 股（按手），第二只同样 500 股
        res = self.run_plan(rows, {"000001": hold("A", 10000, None, None)}, funds=1_000_000.0, members={"000001", "000003", "000004"})
        self.assertEqual([(p["security_code"], p["shares"]) for p in res["plan"]], [("000003", 500), ("000004", 500)])

    def test_adopted_30pct_cap_repays_debt_and_reports_recovery_band(self) -> None:
        self.nav=2_000_000.
        rows=[row('000001','A',100.,101.,90.,2.5),row('000002','B',50.,51.,40.,2.5)]
        holdings={'000001':hold('A',20000,None,None),'000002':hold('B',20000,None,None)}
        result=self.run_plan(rows,holdings,funds=9_000_000.,members=set(holdings),
                             exposure_cap=scan.SEC93_EQUITY_BOND_CAP,cap_cash=-1_000_000.)
        sells=[r for r in result['sells'] if r['rule']=='股债·总仓位上限']
        self.assertEqual([r['sell_shares'] for r in sells],[16000,16000])
        self.assertEqual(result['eb_stock_after'],600000.)
        self.assertEqual(result['cash'],1400000.)
        result['eb']=dict(spread=.032,observed_on='2024-01-05',cap=.3,cash=0.,debt=1_000_000.,source='test')
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()) as output:
            scan.report_section93(result,self.nav,Path(tmp)/'plan.csv','2024-01-08')
        self.assertIn('恢复 ≥3.5%',output.getvalue())
        self.assertIn('沿用受限状态',output.getvalue())

    def test_adopted_30pct_cap_also_limits_new_buys(self) -> None:
        self.nav=1_000_000.
        rows=[row('000001','A',100.,101.,90.,2.5),row('000002','B',100.,95.,90.,.5),
              row('000003','C',100.,95.,90.,.6)]
        holdings={'000001':hold('A',2900,None,None)}
        result=self.run_plan(rows,holdings,funds=9_000_000.,members={'000001', '000002', '000003'},
                             exposure_cap=scan.SEC93_EQUITY_BOND_CAP,cap_cash=710000.)
        self.assertEqual([(r['security_code'],r['shares']) for r in result['plan']],[('000002',100)])
        self.assertEqual(result['eb_stock_after'],300000.)
        self.assertEqual([r['security_code'] for r in result['eb_capped']],['000003'])

    def test_trim_ignores_trend(self) -> None:
        rows = [row("000001", "A", close=100.0, ma20=101.0, ma60=90.0, pv=2.5),
                row("000002", "B", close=100.0, ma20=99.0, ma60=90.0, pv=2.5)]
        holdings = {"000001": hold("A", 5000, 40.0, None), "000002": hold("B", 5000, 40.0, None)}
        res = self.run_plan(rows, holdings, funds=0.0, members={"000001", "000002"})
        rules = {(s["security_code"], s["rule"]) for s in res["sells"]}
        self.assertIn(("000001", "涨幅减持"), rules)        # 涨幅 150%、收盘 < MA20 → 减一档
        self.assertIn(("000002", "涨幅减持"), rules)        # 涨幅 150%、收盘 ≥ MA20 → 同样减一档（v4.132 不看走势）
        a = next(s for s in res["sells"] if s["security_code"] == "000001")
        self.assertEqual(a["sell_shares"], 1500)             # 15 万 ÷ 100 = 1500 股
        self.assertFalse(any("走势闸门" in why for _n, why in res["sell_notes"]))
        self.assertAlmostEqual(res["cash"], 300_000.0)       # 两笔卖出款当日计入可用资金（无可买标的）

    def test_gain_trim_and_residual_clear(self) -> None:
        # P/V 须高于买入线：否则同票当日买卖对冲（NETTABLE）会把减持行冲掉，本例只验卖出侧
        rows = [row("000003", "C", close=100.0, ma20=105.0, ma60=80.0, pv=2.5)]
        holdings = {"000003": hold("C", 1700, 40.0, None)}   # 涨幅 150%；一档 1500 股，减后余 200 ≥ 一手 → 只减 1500
        res = self.run_plan(rows, holdings, funds=0.0, members={"000003"})
        s = res["sells"][0]
        self.assertEqual(s["rule"], "涨幅减持")
        self.assertEqual(s["sell_shares"], 1500)
        holdings = {"000003": hold("C", 1600, 40.0, None)}   # 减 1500 后余 100 < 一手？100 = 一手，不清
        res = self.run_plan(rows, holdings, funds=0.0, members={"000003"})
        self.assertEqual(res["sells"][0]["sell_shares"], 1500)
        holdings = {"000003": hold("C", 1550, 40.0, None)}   # 余 50 < 一手 → 整笔清空
        res = self.run_plan(rows, holdings, funds=0.0, members={"000003"})
        self.assertEqual(res["sells"][0]["sell_shares"], 1550)
        self.assertIn("清空", res["sells"][0]["note"])

    def test_delisted_from_watchlist_reduces_without_trend(self) -> None:
        rows = [row("000004", "D", close=50.0, ma20=40.0, ma60=30.0, pv=0.5)]
        holdings = {"000004": hold("D", 10000, 20.0, None)}
        res = self.run_plan(rows, holdings, funds=0.0, members={"999999"})
        self.assertEqual(res["sells"][0]["rule"], "出名单")
        self.assertEqual(res["sells"][0]["sell_shares"], 3000)

    def test_no_price_stop(self) -> None:
        # v4.222：不设价格止损——收盘低于持仓表止损锚与 MA60 也不出任何卖出行
        rows = [row("000005", "E", close=30.0, ma20=35.0, ma60=33.0, pv=0.8)]
        holdings = {"000005": hold("E", 1000, 28.0, 34.0)}   # 旧口径生效线 = min(34, 33) = 33 > 收盘 30
        res = self.run_plan(rows, holdings, funds=0.0, members={"000005"})
        self.assertEqual(res["sells"], [])
        self.assertAlmostEqual(res["cash"], 0.0)

    def test_gain_trimmed_holding_is_not_swap_source_same_day(self) -> None:
        # v4.134（OI-142）：H1 涨幅 150% 先减一档（1600 股 × 90 = 14.4 万 < 一档），同日不再作涨幅让位源；
        # 换仓改取让位源 H2（v4.222：盈利 43% ≥ 30%、收盘为 MA20 的 1.18 倍 ≥ 1.15）
        cand = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.60)
        h1 = row("000011", "H1", close=90.0, ma20=100.0, ma60=80.0, pv=1.20)
        h2 = row("000012", "H2", close=100.0, ma20=85.0, ma60=80.0, pv=1.50)
        holdings = {"000011": hold("H1", 5000, 36.0, None), "000012": hold("H2", 5000, 70.0, None)}
        res = self.run_plan([cand, h1, h2], holdings, funds=0.0, members={"000010", "000011", "000012"})
        rules = [(s["security_code"], s["rule"]) for s in res["sells"]]
        self.assertEqual(rules, [("000011", "涨幅减持"), ("000012", "换仓")])
        self.assertEqual(res["sells"][0]["sell_shares"], 1600)
        self.assertIn("盈利 43% ≥ 30%", res["sells"][1]["condition"])          # 走让位路径，不是「涨幅 … 让位」
        self.assertEqual(res["sells"][1]["swap_for"], "000010")

    def test_trim_then_swap_most_stretched(self) -> None:
        cand = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.60)
        h1 = row("000011", "H1", close=100.0, ma20=110.0, ma60=90.0, pv=1.20)   # 涨幅 150%（先走涨幅减持）
        h2 = row("000012", "H2", close=100.0, ma20=80.0, ma60=70.0, pv=1.50)    # 盈利 43%、MA20 的 1.25 倍 → 让位源
        holdings = {"000011": hold("H1", 1000, 40.0, None), "000012": hold("H2", 5000, 70.0, None)}
        res = self.run_plan([cand, h1, h2], holdings, funds=1000.0, members={"000010", "000011", "000012"})
        rules = [(s["security_code"], s["rule"]) for s in res["sells"]]
        self.assertEqual(rules, [("000011", "涨幅减持"), ("000012", "换仓")])   # 先减持（清空 1000 股 +10 万仍不足一档）再换仓
        swap = res["sells"][1]
        self.assertEqual(swap["swap_for"], "000010")
        self.assertEqual(swap["sell_shares"], 1500)
        self.assertEqual(len(res["plan"]), 1)
        self.assertEqual(res["plan"][0]["security_code"], "000010")
        self.assertEqual(res["plan"][0]["shares"], 15000)                 # 一档 15 万 ÷ 10 元
        # 无涨幅源时取偏离最大的让位源：H3 为 MA20 的 1.33 倍 > H2 的 1.25 倍；弱势的 H1 不再作卖出源（v4.222）
        h3 = row("000013", "H3", close=100.0, ma20=75.0, ma60=70.0, pv=0.90)
        holdings = {"000011": hold("H1", 5000, 90.0, None), "000012": hold("H2", 5000, 70.0, None),
                    "000013": hold("H3", 5000, 60.0, None)}
        res = self.run_plan([cand, h1, h2, h3], holdings, funds=1000.0, members={"000010", "000011", "000012", "000013"})
        swaps = [s for s in res["sells"] if s["rule"] == "换仓"]
        self.assertEqual(swaps[0]["security_code"], "000013")
        # 偏离不足（MA20 的 1.11 倍 < 1.15）即无让位源，不比 P/V
        h2_flat = row("000012", "H2", close=100.0, ma20=90.0, ma60=80.0, pv=3.00)
        holdings = {"000012": hold("H2", 5000, 70.0, None)}
        res = self.run_plan([cand, h2_flat], holdings, funds=1000.0, members={"000010", "000012"})
        self.assertEqual([s for s in res["sells"] if s["rule"] == "换仓"], [])
        self.assertIn("无满足让位条件的持仓", res["swap_stop_reason"])

    def test_swap_requires_stretched_holding(self) -> None:
        # v4.222：让位源须同时盈利 ≥ 30% 且收盘 ≥ MA20 × 1.15；弱势（收盘 < MA20）不再是卖出理由
        cand = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.60)
        strong = row("000013", "S", close=120.0, ma20=110.0, ma60=90.0, pv=2.0)     # 盈利 20%、MA20 的 1.09 倍 → 不换
        weak = row("000014", "W", close=100.0, ma20=110.0, ma60=90.0, pv=2.0)       # 弱势、盈利 11% → 不换
        holdings = {"000013": hold("S", 5000, 100.0, None), "000014": hold("W", 5000, 90.0, None)}
        res = self.run_plan([cand, strong, weak], holdings, funds=500.0, members={"000010", "000013", "000014"})
        self.assertEqual([s for s in res["sells"] if s["rule"] == "换仓"], [])
        self.assertEqual(res["plan"], [])                                    # 500 元不足一手（1,000 元）
        res = self.run_plan([cand, strong, weak], holdings, funds=1000.0, members={"000010", "000013", "000014"})
        self.assertEqual(res["plan"][0]["shares"], 100)                      # §9.3.1.1 可用资金不足一档时买到用尽

    def test_stretch_source_ignores_pv_margin(self) -> None:
        # v4.222：让位源不比 P/V 边际——持仓侧 0.70 对候选 0.60 差 0.10 < 0.15（旧口径不换），现照换；
        # 持仓侧与候选侧 P/V 不同时报告仍并列两侧
        cand = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.60)
        src = row("000023", "W", close=100.0, ma20=80.0, ma60=70.0, pv=1.50)
        src["hold_pv"] = 0.70
        res = self.run_plan([cand, src], {"000023": hold("W", 5000, 70.0, None)}, funds=1000.0, members={"000010", "000023"})
        self.assertEqual([(s["security_code"], s["hold_pv"]) for s in res["sells"] if s["rule"] == "换仓"], [("000023", 0.70)])
        self.assertEqual([n for n, _h, _c in res["hold_pv_diff"]], ["W"])                # 两侧不同须并列显示

    def test_negative_funds_repays_shortfall_before_buy(self) -> None:
        # §10.2：券商可用保证金为负（已超授信）时 `--funds` 照负值起算，换仓卖出款先补缺口，余额才买入
        trig = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.50)       # 未持仓触发者
        src = row("000012", "H2", close=10.0, ma20=8.0, ma60=7.0, pv=2.00)       # 让位源（盈利 100%、MA20 的 1.25 倍），不过买入线
        holdings = {"000012": hold("H2", 50000, 5.0, None)}
        res = self.run_plan([trig, src], holdings, funds=-50_000.0, members={"000010", "000012"})
        swap = [s for s in res["sells"] if s["rule"] == "换仓"][0]
        self.assertEqual((swap["security_code"], swap["sell_shares"]), ("000012", 15000))   # 卖一档 15 万
        # 15 万卖出款先还 5 万缺口，余 10 万 → 触发者只买 10,000 股（不是一档 15,000 股）
        self.assertEqual([(p["security_code"], p["shares"]) for p in res["plan"]], [("000010", 10000)])
        self.assertAlmostEqual(res["cash"], 0.0)

    def test_negative_funds_without_sale_buys_nothing(self) -> None:
        cand = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.50)
        strong = row("000013", "S", close=10.0, ma20=9.0, ma60=8.0, pv=2.00)     # 盈利 100% 但仅 MA20 的 1.11 倍，无让位源
        res = self.run_plan([cand, strong], {"000013": hold("S", 50000, 5.0, None)}, funds=-50_000.0,
                            members={"000010", "000013"})
        self.assertEqual(res["sells"], [])
        self.assertEqual(res["plan"], [])
        self.assertAlmostEqual(res["cash"], -50_000.0)                            # 缺口原样带出，报告显示仍超授信

    def test_swap_source_block_guards_buy_queue(self) -> None:
        # 研究开关（生产关，K=-1）：临时置 K=1 时当日换仓卖出源不进买入队列；让位源与涨幅源一样没有 P/V 边际，只剔除自身
        trig = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.60)        # 未持仓触发者
        src = row("000012", "H2", close=10.0, ma20=8.0, ma60=7.0, pv=0.95)        # 让位源，自身也过买入线
        near = row("000015", "N", close=10.0, ma20=9.0, ma60=8.0, pv=0.90)        # 让位源没有 P/V 边际（v4.222）→ 不按边际剔除
        ok = row("000014", "A", close=10.0, ma20=9.0, ma60=8.0, pv=0.78)          # 0.78 ≤ 0.80 → 可买
        holdings = {"000012": hold("H2", 50000, 5.0, None)}
        saved = scan.SEC93_SWAP_SOURCE_BLOCK
        scan.SEC93_SWAP_SOURCE_BLOCK = 1.0
        try:
            res = self.run_plan([trig, ok, near, src], holdings, funds=1000.0,
                                members={"000010", "000012", "000014", "000015"})
        finally:
            scan.SEC93_SWAP_SOURCE_BLOCK = saved
        self.assertEqual([s["security_code"] for s in res["sells"] if s["rule"] == "换仓"], ["000012"])
        self.assertEqual([p["security_code"] for p in res["plan"]], ["000010", "000014"])   # 15 万给 X，余 1,000 元买 A 一手
        self.assertEqual(sorted(str(c["security_code"]).zfill(6) for c, _w in res["swap_blocked"]), ["000012"])
        self.assertEqual(res["netted"], [])                                       # 卖出源当日不再买回，无可对冲

    def test_same_day_buy_sell_netted(self) -> None:
        # §9.3.2 第 6 步：同日买卖按较小者抵消，只执行净额（守卫关，换仓卖出源可当日买回）
        trig = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.50)       # 未持仓触发者
        src = row("000012", "H2", close=10.0, ma20=8.0, ma60=7.0, pv=0.80)       # 让位源，自身也过买入线
        holdings = {"000012": hold("H2", 50000, 5.0, None)}
        res = self.run_plan([trig, src], holdings, funds=1000.0, members={"000010", "000012"})
        swap = [s for s in res["sells"] if s["rule"] == "换仓"][0]
        self.assertEqual(swap["security_code"], "000012")
        self.assertEqual(swap["sell_shares"], 14900)                 # 原 15,000 卖出，抵消 100 股
        self.assertIn("同日对冲 100 股", str(swap["note"]))
        self.assertEqual([(p["security_code"], p["shares"]) for p in res["plan"]], [("000010", 15000)])
        self.assertEqual(res["netted"], [("000012", 100.0)])
        self.assertEqual(res["swap_blocked"], [])

    def test_gain_trim_buyback_netted(self) -> None:
        # §9.3.2 第 6 步：涨幅减持后同日买回同样只执行净额
        t = row("000016", "T", close=100.0, ma20=90.0, ma60=80.0, pv=0.50)        # 涨幅 150%、过买入线、走势合格
        holdings = {"000016": hold("T", 5000, 40.0, None)}
        res = self.run_plan([t], holdings, funds=200_000.0, members={"000016"})
        self.assertEqual(res["sells"], [])                                        # 减一档 1500 股与买回 1500 股全额对冲
        self.assertEqual(res["plan"], [])
        self.assertEqual(res["netted"], [("000016", 1500.0)])
        # 出名单是强制退出，不抵消
        gone = row("000013", "G", close=10.0, ma20=9.0, ma60=8.0, pv=0.50)
        res = self.run_plan([gone], {"000013": hold("G", 50000, 5.0, None)}, funds=200000.0, members=set())
        self.assertEqual([s["rule"] for s in res["sells"]], ["出名单"])
        self.assertEqual(res["netted"], [])

    def test_swap_condition_reports_actual_recipients(self) -> None:
        # 报告口径（2026-08-31）：换仓行写卖出款实际去向，触发者降为附注；v4.222 让位源不比 P/V，去向只列名称
        trig = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.60)          # 未持仓触发者
        src = row("000012", "H2", close=100.0, ma20=80.0, ma60=70.0, pv=1.50)       # 让位源
        cheap = row("000014", "A", close=10.0, ma20=9.0, ma60=8.0, pv=0.30)         # 已持仓、更便宜 → 收款
        holdings = {"000012": hold("H2", 5000, 70.0, None), "000014": hold("A", 100, 9.0, None)}
        res = self.run_plan([trig, src, cheap], holdings, funds=1000.0,
                            members={"000010", "000012", "000014"})
        swap = [s for s in res["sells"] if s["rule"] == "换仓"][0]
        self.assertEqual(swap["security_code"], "000012")
        self.assertEqual(swap["swap_for"], "000010")                                 # 机器列仍记触发者
        self.assertIn("盈利 43% ≥ 30% 且收盘为 MA20 的 1.250 倍 ≥ 1.15", swap["condition"])
        self.assertIn("卖出款去向：A、X", swap["condition"])                          # 按 P/V 升序的实际接收方
        self.assertIn("触发闸门：X 0.6000", swap["condition"])
        self.assertNotIn("边际", swap["condition"])
        # 卖出款一分未投出时明写（唯一候选一手 20 万 > 卖出款 15 万）
        pricey = row("000010", "X", close=2000.0, ma20=1800.0, ma60=1700.0, pv=0.50)
        holdings = {"000012": hold("H2", 5000, 70.0, None)}
        res = self.run_plan([pricey, src], holdings, funds=1.0, members={"000010", "000012"})
        swap = [s for s in res["sells"] if s["rule"] == "换仓"][0]
        self.assertEqual(res["plan"], [])
        self.assertIn("卖出款去向：无——卖出款当日未投出", swap["condition"])

    def test_plan_does_not_start_cooldown(self) -> None:
        pricey = row("000020", "P", close=2000.0, ma20=1900.0, ma60=1800.0, pv=0.5)   # 一手 20 万 > 一档 15 万
        counters: dict[str, int] = {}
        res = self.run_plan([pricey], {}, funds=1_000_000.0, members={"000020"}, counters=counters)
        self.assertEqual(len(res["plan"]), 1)
        self.assertEqual(res["plan"][0]["shares"], 100)
        self.assertEqual(res["plan"][0]["cooldown_skips"], 0)      # round(1.33) − 1 = 0
        pricier = row("000021", "Q", close=4500.0, ma20=4000.0, ma60=3500.0, pv=0.5)  # x = 3 → 跳过 2 次
        counters = {}
        res = self.run_plan([pricier], {}, funds=1_000_000.0, members={"000021"}, counters=counters)
        self.assertEqual(res["plan"][0]["cooldown_skips"], 2)
        self.assertEqual(counters, {})
        counters["000021"] = 2  # 独立成交确认后读入的状态
        res = self.run_plan([pricier], {}, funds=1_000_000.0, members={"000021"}, counters=counters)
        self.assertEqual(res["plan"], [])                            # 冷却中跳过
        self.assertEqual(counters["000021"], 1)
        res = self.run_plan([pricier], {}, funds=1_000_000.0, members={"000021"}, counters=counters)
        self.assertEqual(counters["000021"], 0)
        res = self.run_plan([pricier], {}, funds=1_000_000.0, members={"000021"}, counters=counters)
        self.assertEqual(len(res["plan"]), 1)                        # 计数归零后再买一手

    def test_cooldown_sell_side_counts_trim(self) -> None:
        pricey = row("000022", "R", close=4500.0, ma20=4600.0, ma60=3500.0, pv=3.0)   # 涨幅 350% 且弱势
        holdings = {"000022": hold("R", 300, 1000.0, None)}
        buy: dict[str, int] = {}
        sell: dict[str, int] = {}
        res = self.run_plan([pricey], holdings, funds=0.0, members={"000022"}, counters=buy, sell_counters=sell)
        self.assertEqual(res["sells"][0]["sell_shares"], 100)        # 一档不足一手 → 按手减
        self.assertEqual(sell, {})
        self.assertEqual(buy, {})                                    # 卖出冷却不写买入侧
        sell["000022"] = 2  # 独立成交确认后读入的状态
        holdings = {"000022": hold("R", 200, 1000.0, None)}
        res = self.run_plan([pricey], holdings, funds=0.0, members={"000022"}, counters=buy, sell_counters=sell)
        self.assertEqual([s for s in res["sells"] if s["rule"] == "涨幅减持"], [])   # 冷却中跳过
        self.assertEqual(sell["000022"], 1)

    def test_cooldown_buy_side_does_not_block_trim(self) -> None:
        pricey = row("000022", "R", close=4500.0, ma20=4600.0, ma60=3500.0, pv=3.0)   # 涨幅 350% 且弱势
        holdings = {"000022": hold("R", 300, 1000.0, None)}
        buy = {"000022": 2}                                          # 买入侧冷却中
        sell: dict[str, int] = {}
        res = self.run_plan([pricey], holdings, funds=0.0, members={"000022"}, counters=buy, sell_counters=sell)
        self.assertEqual(res["sells"][0]["rule"], "涨幅减持")          # 减持照常
        self.assertEqual(res["sells"][0]["sell_shares"], 100)
        self.assertEqual(buy["000022"], 2)                           # 买入侧计数不被消费
        self.assertEqual(sell, {})

    def test_missing_quote_holding_is_flagged_not_silent(self) -> None:
        holdings = {"000030": hold("M", 1000, 10.0, 9.0)}
        res = self.run_plan([], holdings, funds=0.0, members={"000030"})
        self.assertEqual(res["sells"][0]["rule"], "数据缺失")
        self.assertEqual(res["missing_holdings"], ["M"])

    def test_new_entry_requires_stabilized_low(self) -> None:
        # v4.222 新建仓走势：近 3 日未创 20 日新低且收盘 > MA5、> MA20，不再要求 MA20 > MA60；已有持仓加仓仍须 MA20 > MA60
        ok = row("000040", "N", close=10.0, ma20=9.5, ma60=11.0, pv=0.5)             # MA20 < MA60 也可新建仓
        self.assertTrue(scan.buy_trend_ok(ok, set()))
        self.assertFalse(scan.buy_trend_ok(ok, {"000040"}))                          # 加仓看 MA20 > MA60
        self.assertFalse(scan.buy_trend_ok(row("000041", "L", 10.0, 9.5, 9.0, 0.5, bt_stable=False), set()))   # 近 3 日创新低
        self.assertFalse(scan.buy_trend_ok(row("000042", "M", 10.0, 9.5, 9.0, 0.5, ma5=10.2), set()))         # 收盘 ≤ MA5
        self.assertFalse(scan.buy_trend_ok(row("000043", "K", 10.0, 10.5, 9.0, 0.5), set()))                  # 收盘 ≤ MA20
        self.assertFalse(scan.buy_trend_ok(row("000044", "S", 10.0, 9.5, 9.0, 0.5, bt_stable="False"), set()))  # CSV 字符串

    def test_new_low20_and_stabilized_flags(self) -> None:
        # 逐日「最低价为含当日 20 日最低价的最小值」与近 3 日走稳，与回测 _bt_low_series_all／stabilized 同式
        rows = [{"date": f"d{i:02d}", "close": 10.0 + i * 0.01, "low": 9.0 + i * 0.01, "volume": 1.0, "amount": 1.0}
                for i in range(64)]
        rows[61]["low"] = 8.0                                                       # 第 62 根创 20 日新低
        scan.add_indicators(rows)
        self.assertTrue(rows[61]["new_low20"])
        self.assertFalse(rows[62]["new_low20"])
        self.assertFalse(scan.quote_snapshot(rows)["bt_stable"])                      # 新低在近 3 根内
        rows2 = rows + [dict(rows[-1], date="d64"), dict(rows[-1], date="d65")]
        for r in rows2[64:]:
            r.pop("new_low20", None)
        scan.add_indicators(rows2)
        self.assertTrue(scan.quote_snapshot(rows2)["bt_stable"])                      # 新低已在 3 根之外
        self.assertAlmostEqual(scan.quote_snapshot(rows2)["ma5"], sum(r["close"] for r in rows2[-5:]) / 5)

    def test_holding_trim_signal_shared_helper(self) -> None:
        self.assertEqual(scan.holding_trim_signal(100.0, 99.0, 40.0)[0], "涨幅减持")   # 收盘 ≥ MA20 也减（v4.132 不看走势）
        self.assertEqual(scan.holding_trim_signal(100.0, 101.0, 40.0)[0], "涨幅减持")  # 涨幅 150% ≥ 110%
        self.assertEqual(scan.holding_trim_signal(100.0, 101.0, 50.0)[0], "")           # 涨幅 100% < 110%
        self.assertEqual(scan.holding_trim_signal(100.0, None, 40.0)[0], "涨幅减持")   # MA20 缺失不影响


if __name__ == "__main__":
    unittest.main()
