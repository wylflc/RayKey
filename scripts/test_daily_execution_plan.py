#!/usr/bin/env python3
"""§9.3.2 执行清单（先卖后买）与 §9.3.3 冷却计数器的无网络回归。"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import screen_daily_volume_price_signals as scan


def row(code: str, name: str, close: float, ma20: float, ma60: float, pv: float | None,
        amount_ma20: float = 1e8) -> dict:
    r = {"security_code": code, "security_name": name, "close": close, "ma20": ma20, "ma60": ma60,
         "amount_ma20": amount_ma20, "model_intrinsic_value": (close / pv) if pv else "",
         "model_band_source": "模型带", "quality_tier": "L2"}
    if pv is not None:
        r["model_pv"] = pv
    return r


def hold(name: str, shares: float, cost: float | None, stop: float | None) -> dict:
    return {"name": name, "shares": shares, "cost": cost, "stop": stop}


class ExecutionPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        scan.CLOSE_SERIES.clear()      # 无K线序列 → 相关性未知 → 放行（OI-093 语义）
        self.nav = 3_000_000.0        # 一档 15 万

    def run_plan(self, rows, holdings, funds, members=None, counters=None, holding_rows=None, sell_counters=None):
        return scan.section93_execution_plan(rows, self.nav, funds, holdings, set(), set(),
                                             members, counters if counters is not None else {}, holding_rows,
                                             sell_counters=sell_counters)

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

    def test_stop_review_row_is_conditional(self) -> None:
        rows = [row("000005", "E", close=30.0, ma20=35.0, ma60=33.0, pv=0.8)]
        holdings = {"000005": hold("E", 1000, 28.0, 34.0)}   # 生效线 = min(34, 33) = 33 > 收盘 30
        res = self.run_plan(rows, holdings, funds=0.0, members={"000005"})
        s = next(x for x in res["sells"] if x["rule"] == "止损复核")
        self.assertEqual(s["stop_line"], 33.0)
        self.assertEqual(s["sell_shares"], 1000)
        self.assertAlmostEqual(res["cash"], 0.0)             # 止损候选卖出款不计入买入预算

    def test_trim_then_swap_priciest_weak(self) -> None:
        cand = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.60)
        h1 = row("000011", "H1", close=100.0, ma20=110.0, ma60=90.0, pv=1.20)   # 弱势、涨幅 150%（先走涨幅减持）
        h2 = row("000012", "H2", close=100.0, ma20=110.0, ma60=90.0, pv=1.50)   # 弱势、最贵
        holdings = {"000011": hold("H1", 1000, 40.0, None), "000012": hold("H2", 5000, 90.0, None)}
        res = self.run_plan([cand, h1, h2], holdings, funds=1000.0, members={"000010", "000011", "000012"})
        rules = [(s["security_code"], s["rule"]) for s in res["sells"]]
        self.assertEqual(rules, [("000011", "涨幅减持"), ("000012", "换仓")])   # 先减持（清空 1000 股 +10 万仍不足一档）再换仓
        swap = res["sells"][1]
        self.assertEqual(swap["swap_for"], "000010")
        self.assertEqual(swap["sell_shares"], 1500)
        self.assertEqual(len(res["plan"]), 1)
        self.assertEqual(res["plan"][0]["security_code"], "000010")
        self.assertEqual(res["plan"][0]["shares"], 15000)                 # 一档 15 万 ÷ 10 元
        # 无涨幅源时换最贵弱势持仓，且须满足换仓差
        holdings = {"000011": hold("H1", 5000, 90.0, None), "000012": hold("H2", 5000, 90.0, None)}
        res = self.run_plan([cand, h1, h2], holdings, funds=1000.0, members={"000010", "000011", "000012"})
        swaps = [s for s in res["sells"] if s["rule"] == "换仓"]
        self.assertEqual(swaps[0]["security_code"], "000012")
        cand_close = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.90)   # 与 H2 P/V 1.00 差 0.10 < 0.15
        h2_close = row("000012", "H2", close=100.0, ma20=110.0, ma60=90.0, pv=1.00)
        holdings = {"000012": hold("H2", 5000, 90.0, None)}
        res = self.run_plan([cand_close, h2_close], holdings, funds=1000.0, members={"000010", "000012"})
        self.assertEqual([s for s in res["sells"] if s["rule"] == "换仓"], [])
        self.assertIn("<", res["swap_stop_reason"])

    def test_swap_requires_weak_holding(self) -> None:
        cand = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.60)
        strong = row("000013", "S", close=120.0, ma20=110.0, ma60=90.0, pv=2.0)     # 收盘 ≥ MA20 且涨幅 20% → 不换
        holdings = {"000013": hold("S", 5000, 100.0, None)}
        res = self.run_plan([cand, strong], holdings, funds=500.0, members={"000010", "000013"})
        self.assertEqual([s for s in res["sells"] if s["rule"] == "换仓"], [])
        self.assertEqual(res["plan"], [])                                    # 500 元不足一手（1,000 元）
        res = self.run_plan([cand, strong], holdings, funds=1000.0, members={"000010", "000013"})
        self.assertEqual(res["plan"][0]["shares"], 100)                      # §9.3.1.1 可用资金不足一档时买到用尽

    def test_holding_side_pv_governs_swap_source(self) -> None:
        # v4.92 SPA：换仓来源按持仓侧 `hold_pv` 判；候选侧 `model_pv` 只管买入线与候选排序
        # 候选 0.60 对持仓侧 0.70 差 0.10 < 0.15 不换（按候选侧 1.50 会误换）
        cand = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.60)
        weak = row("000023", "W", close=100.0, ma20=110.0, ma60=90.0, pv=1.50)
        weak["hold_pv"] = 0.70
        res = self.run_plan([cand, weak], {"000023": hold("W", 5000, 90.0, None)}, funds=1000.0, members={"000010", "000023"})
        self.assertEqual([s for s in res["sells"] if s["rule"] == "换仓"], [])
        self.assertIn("持仓侧 P/V 0.7000", res["swap_stop_reason"])
        self.assertEqual([n for n, _h, _c in res["hold_pv_diff"]], ["W"])                # 两侧不同须并列显示
        weak["hold_pv"] = 1.50
        res = self.run_plan([cand, weak], {"000023": hold("W", 5000, 90.0, None)}, funds=1000.0, members={"000010", "000023"})
        self.assertEqual([(s["security_code"], s["hold_pv"]) for s in res["sells"] if s["rule"] == "换仓"], [("000023", 1.50)])
        self.assertEqual(res["hold_pv_diff"], [])                                       # 两侧相同时不列差异

    def test_negative_funds_repays_shortfall_before_buy(self) -> None:
        # §10.2：券商可用保证金为负（已超授信）时 `--funds` 照负值起算，换仓卖出款先补缺口，余额才买入
        trig = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.50)       # 未持仓触发者
        src = row("000012", "H2", close=10.0, ma20=12.0, ma60=9.0, pv=2.00)      # 弱势卖出源，不过买入线
        holdings = {"000012": hold("H2", 50000, 5.0, None)}
        res = self.run_plan([trig, src], holdings, funds=-50_000.0, members={"000010", "000012"})
        swap = [s for s in res["sells"] if s["rule"] == "换仓"][0]
        self.assertEqual((swap["security_code"], swap["sell_shares"]), ("000012", 15000))   # 卖一档 15 万
        # 15 万卖出款先还 5 万缺口，余 10 万 → 触发者只买 10,000 股（不是一档 15,000 股）
        self.assertEqual([(p["security_code"], p["shares"]) for p in res["plan"]], [("000010", 10000)])
        self.assertAlmostEqual(res["cash"], 0.0)

    def test_negative_funds_without_sale_buys_nothing(self) -> None:
        cand = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.50)
        strong = row("000013", "S", close=10.0, ma20=9.0, ma60=8.0, pv=2.00)     # 持仓走势未坏，无可换出源
        res = self.run_plan([cand, strong], {"000013": hold("S", 50000, 5.0, None)}, funds=-50_000.0,
                            members={"000010", "000013"})
        self.assertEqual(res["sells"], [])
        self.assertEqual(res["plan"], [])
        self.assertAlmostEqual(res["cash"], -50_000.0)                            # 缺口原样带出，报告显示仍超授信

    def test_same_day_buy_sell_netted(self) -> None:
        # §9.3.2 第 6 步：同日买卖按较小者抵消，只执行净额
        trig = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.50)       # 未持仓触发者
        src = row("000012", "H2", close=10.0, ma20=12.0, ma60=9.0, pv=0.80)      # 弱势卖出源，自身也过买入线
        holdings = {"000012": hold("H2", 50000, 5.0, None)}
        res = self.run_plan([trig, src], holdings, funds=1000.0, members={"000010", "000012"})
        swap = [s for s in res["sells"] if s["rule"] == "换仓"][0]
        self.assertEqual(swap["security_code"], "000012")
        self.assertEqual(swap["sell_shares"], 14900)                 # 原 15,000 卖出，抵消 100 股
        self.assertIn("同日对冲 100 股", str(swap["note"]))
        self.assertEqual([(p["security_code"], p["shares"]) for p in res["plan"]], [("000010", 15000)])
        self.assertEqual(res["netted"], [("000012", 100.0)])
        # 出名单是强制退出，不抵消
        gone = row("000013", "G", close=10.0, ma20=9.0, ma60=8.0, pv=0.50)
        res = self.run_plan([gone], {"000013": hold("G", 50000, 5.0, None)}, funds=200000.0, members=set())
        self.assertEqual([s["rule"] for s in res["sells"]], ["出名单"])
        self.assertEqual(res["netted"], [])

    def test_swap_condition_reports_actual_recipients(self) -> None:
        # 报告口径（2026-08-31）：换仓行依据写对**实际接收方**的边际，触发者降为附注
        trig = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.60)          # 未持仓触发者
        src = row("000012", "H2", close=100.0, ma20=110.0, ma60=90.0, pv=1.50)      # 弱势最贵 → 卖出源
        cheap = row("000014", "A", close=10.0, ma20=9.0, ma60=8.0, pv=0.30)         # 已持仓、更便宜 → 收款
        holdings = {"000012": hold("H2", 5000, 90.0, None), "000014": hold("A", 100, 9.0, None)}
        res = self.run_plan([trig, src, cheap], holdings, funds=1000.0,
                            members={"000010", "000012", "000014"})
        swap = [s for s in res["sells"] if s["rule"] == "换仓"][0]
        self.assertEqual(swap["security_code"], "000012")
        self.assertEqual(swap["swap_for"], "000010")                                 # 机器列仍记触发者
        self.assertIn("持仓侧 P/V 1.5000 且弱势", swap["condition"])
        self.assertIn("卖出款去向：", swap["condition"])
        self.assertIn("A 0.3000（边际 +1.2000）", swap["condition"])                  # 对实际接收方的边际
        # 边际写死过一次（v4.120 由 0.19 改 0.18 时漏改），改从在册常量取
        self.assertIn(f"触发闸门：X 0.6000（差 0.9000 ≥ {scan.SEC93_SWAP_MARGIN:.4f}）", swap["condition"])
        # 接收方边际不足时打标：源持仓侧 0.70，接收方 0.60 → 差 0.10 < 边际（触发者 0.40 差 0.30 过线）
        trig2 = row("000010", "X", close=10.0, ma20=9.0, ma60=8.0, pv=0.40)
        src2 = row("000012", "H2", close=100.0, ma20=110.0, ma60=90.0, pv=1.50)
        src2["hold_pv"] = 0.70
        near = row("000015", "N", close=10.0, ma20=9.0, ma60=8.0, pv=0.60)
        holdings = {"000012": hold("H2", 5000, 90.0, None), "000015": hold("N", 100, 9.0, None)}
        res = self.run_plan([trig2, src2, near], holdings, funds=1000.0,
                            members={"000010", "000012", "000015"})
        swap = [s for s in res["sells"] if s["rule"] == "换仓"][0]
        self.assertIn("N 0.6000（边际 +0.1000⚠不足）", swap["condition"])
        self.assertIn("X 0.4000（边际 +0.3000）", swap["condition"])                  # 触发者本身过线、不打标
        # 卖出款一分未投出时明写（唯一候选一手 20 万 > 卖出款 15 万）
        pricey = row("000010", "X", close=2000.0, ma20=1800.0, ma60=1700.0, pv=0.50)
        holdings = {"000012": hold("H2", 5000, 90.0, None)}
        res = self.run_plan([pricey, src], holdings, funds=1.0, members={"000010", "000012"})
        swap = [s for s in res["sells"] if s["rule"] == "换仓"][0]
        self.assertEqual(res["plan"], [])
        self.assertIn("卖出款去向：无——卖出款当日未投出", swap["condition"])

    def test_cooldown_counter_consumed_and_set(self) -> None:
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
        self.assertEqual(counters["000021"], 2)
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
        self.assertEqual(sell["000022"], 2)
        self.assertEqual(buy, {})                                    # 卖出冷却不写买入侧
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
        self.assertEqual(sell["000022"], 2)

    def test_cooldown_state_round_trip_by_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cooldown.csv"
            before = {"buy": {"000021": 2}, "sell": {"000022": 3}}
            after = {"buy": {"000021": 1}, "sell": {"000022": 2, "000023": 1}}
            scan.save_cooldown_state(path, before, after, {"000021": "P", "000022": "R", "000023": "S"}, "2026-09-02")
            state, names, writable = scan.load_cooldown_state(path, "2026-09-03")
            self.assertTrue(writable)
            self.assertEqual(state, {"buy": {"000021": 1}, "sell": {"000022": 2, "000023": 1}})
            state, _names, _w = scan.load_cooldown_state(path, "2026-09-02")   # 同日重跑从 remaining_before 重算
            self.assertEqual(state, {"buy": {"000021": 2}, "sell": {"000022": 3}})

    def test_missing_quote_holding_is_flagged_not_silent(self) -> None:
        holdings = {"000030": hold("M", 1000, 10.0, 9.0)}
        res = self.run_plan([], holdings, funds=0.0, members={"000030"})
        self.assertEqual(res["sells"][0]["rule"], "数据缺失")
        self.assertEqual(res["missing_holdings"], ["M"])

    def test_cooldown_state_roundtrip_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cd.csv"
            scan.save_cooldown_state(path, {"buy": {"000001": 0}}, {"buy": {"000001": 2}}, {"000001": "A"}, "2026-08-24")
            empty = {"buy": {}, "sell": {}}
            counters, names, writable = scan.load_cooldown_state(path, "2026-08-24")
            self.assertEqual(counters, empty)                        # 同日重跑：从 remaining_before 起算
            self.assertTrue(writable)
            counters, _n, writable = scan.load_cooldown_state(path, "2026-08-25")
            self.assertEqual(counters, {"buy": {"000001": 2}, "sell": {}})
            counters, _n, writable = scan.load_cooldown_state(path, "2026-08-20")
            self.assertEqual(counters, empty)
            self.assertFalse(writable)                               # 历史重放：不应用不回写
            with path.open(encoding="utf-8") as fh:
                self.assertEqual(list(csv.DictReader(fh))[0]["security_name"], "A")

    def test_holding_trim_signal_shared_helper(self) -> None:
        self.assertEqual(scan.holding_trim_signal(100.0, 99.0, 40.0)[0], "涨幅减持")   # 收盘 ≥ MA20 也减（v4.132 不看走势）
        self.assertEqual(scan.holding_trim_signal(100.0, 101.0, 40.0)[0], "涨幅减持")  # 涨幅 150% ≥ 110%
        self.assertEqual(scan.holding_trim_signal(100.0, 101.0, 50.0)[0], "")           # 涨幅 100% < 110%
        self.assertEqual(scan.holding_trim_signal(100.0, None, 40.0)[0], "涨幅减持")   # MA20 缺失不影响


if __name__ == "__main__":
    unittest.main()
