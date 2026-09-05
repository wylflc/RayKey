#!/usr/bin/env python3
"""计量口径 m2（工作流 §12.1 第 2 款）：日历年化 CAGR、逐期超额收益 Sharpe、rf 时点对齐、强平缓冲、扫描文件版本头。"""
import math
import statistics
import tempfile
import unittest
from pathlib import Path

import backtest_valuation_strategy as bt
import sweep_backtest_configs as sweep


def curve_from(values, days):
    """(日期, 净值, 现金, 持仓数, 负债, 担保比例, top1, top3) 行；只填指标用到的前两列与占位。"""
    return [(d, v, 0.0, 1, 0.0, float("inf"), 0.0, 0.0) for d, v in zip(days, values)]


class CalendarCagrTest(unittest.TestCase):
    def test_one_calendar_year_doubling_is_100pct(self):
        # 2020 是闰年：366 天 ÷ 365.25 略多于一年，年化略低于 100%；用 2021 全年（365 天）核对量级
        self.assertAlmostEqual(bt.calendar_cagr(100, 200, "2021-01-01", "2022-01-01"), 2 ** (365.25 / 365) - 1, places=9)
        self.assertAlmostEqual(bt.calendar_cagr(100, 400, "2020-01-01", "2022-01-01"),
                               4 ** (365.25 / 731) - 1, places=9)

    def test_degenerate_inputs_are_nan(self):
        self.assertTrue(math.isnan(bt.calendar_cagr(100, 120, "2021-01-01", "2021-01-01")))
        self.assertTrue(math.isnan(bt.calendar_cagr(100, 0, "2021-01-01", "2022-01-01")))
        self.assertTrue(math.isnan(bt.calendar_cagr(0, 100, "2021-01-01", "2022-01-01")))

    def test_summary_uses_calendar_years_and_keeps_244_bridge(self):
        days = ["2020-01-02", "2020-01-03", "2020-01-06", "2021-01-04"]
        values = [100.0, 101.0, 99.0, 130.0]
        result = {"equity": curve_from(values, days), "closed": [], "buys": 0, "sells": 0, "turnover": 0.0,
                  "margin_events": [], "min_margin_ratio": float("inf")}
        summary = bt.summarize("t", result, 100.0, {}, [])
        self.assertEqual(summary["计量版本"], bt.METRIC_VERSION)
        self.assertAlmostEqual(summary["年化"], bt.calendar_cagr(100.0, 130.0, days[0], days[-1]))
        self.assertAlmostEqual(summary["年化_交易日口径"], 1.3 ** (244 / 4) - 1)
        self.assertEqual(summary["首个净值日"], days[0])
        self.assertEqual(summary["末次净值日"], days[-1])
        self.assertTrue(math.isnan(summary["最低股票同跌缓冲"]))      # 无负债路径：不适用
        self.assertEqual(summary["最低担保比例日"], "")
        self.assertEqual(summary["rf覆盖率"], 0.0)                   # 没给 rf 文件：覆盖率 0
        self.assertAlmostEqual(summary["Calmar"], summary["年化"] / summary["最大回撤"])


class SharpeTest(unittest.TestCase):
    days = ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08", "2021-01-11"]
    values = [100.0, 101.0, 100.5, 102.0, 101.0, 103.0]

    def test_matches_manual_excess_mean_over_sample_stdev(self):
        rf = [("2020-12-31", 0.0365)]
        curve = curve_from(self.values, self.days)
        sharpe, coverage = bt.sharpe_ratio(curve, *bt.rf_series(rf))
        excess = []
        for i in range(1, len(curve)):
            d0, d1 = self.days[i - 1], self.days[i]
            gap = bt._days_between(d0, d1)
            excess.append(self.values[i] / self.values[i - 1] - 1 - 0.0365 * gap / 365.25)
        self.assertAlmostEqual(sharpe, statistics.fmean(excess) / statistics.stdev(excess) * math.sqrt(244))
        self.assertEqual(coverage, 1.0)
        # 周末跨 3 个日历日的那一期计 3 天利息，而不是 1 天
        self.assertEqual(bt._days_between("2021-01-08", "2021-01-11"), 3)

    def test_rf_is_not_backfilled_and_coverage_is_reported(self):
        # 利率首次观测在第 3 个净值日：前两期没有可得利率 → 按 0 计，覆盖率 3/5
        rf = [("2021-01-06", 0.02)]
        curve = curve_from(self.values, self.days)
        sharpe, coverage = bt.sharpe_ratio(curve, *bt.rf_series(rf))
        self.assertAlmostEqual(coverage, 3 / 5)
        excess = []
        for i in range(1, len(curve)):
            d0, d1 = self.days[i - 1], self.days[i]
            r = 0.02 * bt._days_between(d0, d1) / 365.25 if d0 >= "2021-01-06" else 0.0
            excess.append(self.values[i] / self.values[i - 1] - 1 - r)
        self.assertAlmostEqual(sharpe, statistics.fmean(excess) / statistics.stdev(excess) * math.sqrt(244))
        # 观测日等于期首日 d0 即视为可得（bisect_right）；晚于 d0 的观测不用于该期
        rf_late = [("2021-01-05", 0.02)]
        _s, cov_late = bt.sharpe_ratio(curve, *bt.rf_series(rf_late))
        self.assertAlmostEqual(cov_late, 4 / 5)

    def test_short_or_flat_series_is_nan(self):
        self.assertTrue(math.isnan(bt.sharpe_ratio(curve_from([1, 1.1, 1.2], self.days[:3]), [], [])[0]))
        flat = curve_from([1.0] * 6, self.days)
        sharpe, coverage = bt.sharpe_ratio(flat, [], [])
        self.assertTrue(math.isnan(sharpe))
        self.assertEqual(coverage, 0.0)

    def test_rolling_window_shares_the_full_period_function(self):
        # 月末锚定的 3 年窗：随便造一条 4 年日线，窗口 Sharpe 必须等于同一切片上的 sharpe_ratio
        from datetime import date, timedelta
        d, days = date(2018, 1, 2), []
        while d <= date(2022, 1, 31):
            if d.weekday() < 5:
                days.append(d.isoformat())
            d += timedelta(days=1)
        values = [100 * (1 + 0.0003) ** i * (1 + 0.01 * math.sin(i / 7)) for i in range(len(days))]
        curve = curve_from(values, days)
        rf = [("2017-12-29", 0.03), ("2019-06-28", 0.025), ("2021-03-31", 0.02)]
        windows = bt.rolling_windows(curve, years=3, risk_free=rf)
        self.assertTrue(windows)
        idx = {row[0]: i for i, row in enumerate(curve)}
        rf_dates, rf_vals = bt.rf_series(rf)
        for w in windows:
            j, i = idx[w["start"]], idx[w["end"]]
            self.assertAlmostEqual(w["sharpe"], bt.sharpe_ratio(curve[j:i + 1], rf_dates, rf_vals)[0])


class LiquidationBufferTest(unittest.TestCase):
    def test_total_asset_and_stock_only_buffers(self):
        # 无现金：两种缓冲相等 = 1 − k/R
        total, stock = bt.liquidation_buffers(stock=200.0, cash=0.0, debt=100.0, maintenance=1.3)
        self.assertAlmostEqual(total, 1 - 1.3 / 2.0)
        self.assertAlmostEqual(stock, (200 - 130) / 200)
        # 有现金：股票同跌缓冲 (S + C − kD)/S 大于总资产冲击缓冲 1 − k/R
        total, stock = bt.liquidation_buffers(200.0, 50.0, 100.0, 1.3)
        self.assertAlmostEqual(total, 1 - 1.3 / 2.5)
        self.assertAlmostEqual(stock, (250 - 130) / 200)
        self.assertGreater(stock, total)

    def test_not_applicable_and_negative_values(self):
        self.assertTrue(all(math.isnan(v) for v in bt.liquidation_buffers(200.0, 0.0, 0.0, 1.3)))
        total, stock = bt.liquidation_buffers(0.0, 50.0, 100.0, 1.3)
        self.assertTrue(math.isnan(stock))
        self.assertAlmostEqual(total, 1 - 1.3 / 0.5)
        # 已触线（R < k）：负缓冲原样保留，不截为 0
        total, stock = bt.liquidation_buffers(100.0, 0.0, 100.0, 1.3)
        self.assertLess(total, 0)
        self.assertLess(stock, 0)


class ScanFileVersionTest(unittest.TestCase):
    def write(self, lines):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        tmp.write("\n".join(lines) + "\n")
        tmp.close()
        return Path(tmp.name)

    def row(self, label, since, fields, value=0.1):
        return "|".join([label, since] + [f"{value:.6f}"] * len(fields))

    def test_header_declares_version_and_fields(self):
        path = self.write([sweep.metric_header(), self.row("BASE", "2011-11-01", sweep.FIELDS),
                           "#EX5|2011-11-01|000001", self.row("EX5:BASE", "2011-11-01", sweep.FIELDS),
                           "X|2011-11-01|ERR"])
        groups, orders, failed, note, version, fields = sweep.load_scan(path)
        self.assertEqual(version, sweep.METRIC_VERSION)
        self.assertEqual(fields, sweep.FIELDS)
        self.assertEqual(orders[""], ["BASE"])
        self.assertIn("2011-11-01", groups[sweep.EX5_PREFIX]["BASE"])
        self.assertEqual(failed[""]["X"], 1)
        self.assertIn("000001", note)

    def test_headerless_files_are_inferred_by_width(self):
        legacy = self.write([self.row("BASE", "2011-11-01", sweep.FIELDS_M1)])
        self.assertEqual(sweep.load_scan(legacy)[4], "m1")
        current = self.write([self.row("BASE", "2011-11-01", sweep.FIELDS)])
        self.assertEqual(sweep.load_scan(current)[4], sweep.METRIC_VERSION)
        mixed = self.write([self.row("BASE", "2011-11-01", sweep.FIELDS_M1), self.row("BASE", "2012-05-01", sweep.FIELDS)])
        with self.assertRaises(SystemExit):
            sweep.load_scan(mixed)

    def test_date_fields_round_trip(self):
        self.assertEqual(sweep._field_value({"最低担保比例日": "2015-06-09"}, "最低担保比例日"), 20150609.0)
        self.assertEqual(sweep._field_value({"最低担保比例日": ""}, "最低担保比例日"), 0.0)
        self.assertEqual(sweep._date_str(20150609.0), "2015-06-09")
        self.assertEqual(sweep._date_str(0.0), "—")
        self.assertTrue(math.isinf(sweep._field_value({"最低担保比例": "inf"}, "最低担保比例")))
        self.assertTrue(math.isnan(sweep._field_value({"最低股票同跌缓冲": "nan"}, "最低股票同跌缓冲")))

    def test_fields_are_a_superset_of_m1_and_cover_the_tail_table(self):
        self.assertEqual(sweep.FIELDS[:len(sweep.FIELDS_M1)], sweep.FIELDS_M1)
        for key in ("强平次数", "最低担保比例", "最低股票同跌缓冲", "最低总资产冲击缓冲", "rf覆盖率",
                    "年化_交易日口径", "滚动5年年化最差窗口末日", "最大回撤起日", "最大回撤止日", "末次净值日"):
            self.assertIn(key, sweep.FIELDS)
        self.assertTrue(sweep.DATE_FIELDS <= set(sweep.FIELDS))


class WorkflowTextTest(unittest.TestCase):
    def test_clause_2_states_the_m2_caliber(self):
        text = (Path(__file__).resolve().parents[1] / "docs/000_Ashare_workflow.md").read_text(encoding="utf-8")
        self.assertIn(f"现行 {bt.METRIC_VERSION}）", text)
        self.assertIn("全期 CAGR = (期末净资产 ÷ 初始资本)^(365.25 ÷ 首个与末次净值日的日历天数) − 1", text)
        self.assertIn("逐日超额简单收益均值 ÷ 样本标准差 × √244", text)
        self.assertIn("股票同跌缓冲 = (S + C − kD) ÷ S", text)
        self.assertIn("**跨起点尾部**", text)
        self.assertIn("【决策读数】（全样本与剔除集 A 各一份）、【采纳判定】、【跨起点尾部】", text)


if __name__ == "__main__":
    unittest.main()
