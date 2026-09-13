"""§12.1 第 2 款采纳判定（`sweep_backtest_configs.adoption_verdict`）：四读数双表、回撤通道（v4.175）、闸门／否决；
OI-172 完整性校验（起点集合、同窗窗口集合、有限值）与 OI-173 否决只数「负窗由 0 转正」。"""
import math
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sweep_backtest_configs as sw  # noqa: E402

STARTS = ("2009-11-01", "2010-05-01", "2015-11-01", "2016-05-01")
WIN = ("2015-01", "2015-02", "2015-03")
# BASE 各起点的最大回撤区间：前两个起点 2015 股灾、后两个起点 2020 年初，两段互不重叠
BASE_DD = {"2009-11-01": (20150612, 20160201), "2010-05-01": (20150609, 20160613),
           "2015-11-01": (20200103, 20200323), "2016-05-01": (20200114, 20200323)}


def row(cagr=0.40, mdd=0.65, dd=(20150612, 20160201), win=0.50, worst=0.10, r5dd=0.45, neg=0.0):
    return {"年化": cagr, "最大回撤": mdd, "最大回撤起日": float(dd[0]), "最大回撤止日": float(dd[1]),
            sw.WIN5_KEY: {m: win for m in WIN}, "滚动5年年化最差": worst, "滚动5年回撤中位": r5dd,
            "滚动5年为负的窗口占比": neg}


def arms(main=0.0, cagr=0.0, mdd=0.0, worst=0.02, mdd_starts=STARTS, r5dd=0.0, main_ex=None, cagr_ex=None, mdd_ex=None):
    """全样本／去赢家两表：候选相对 BASE 的配对差按参数给（去赢家表缺省同全样本）。"""
    def table(dm, dc, dd):
        base = {s: row(dd=BASE_DD[s]) for s in STARTS}
        cand = {s: row(cagr=0.40 + dc, mdd=0.65 + (dd if s in mdd_starts else 0.0), dd=BASE_DD[s],
                       win=0.50 + dm, worst=0.10 + worst, r5dd=0.45 + r5dd) for s in STARTS}
        return {"BASE": base, "CAND": cand}
    return (table(main, cagr, mdd),
            table(main if main_ex is None else main_ex, cagr if cagr_ex is None else cagr_ex, mdd if mdd_ex is None else mdd_ex))


class AdoptionVerdictTest(unittest.TestCase):
    def verdict(self, *a, **k):
        full, ex = arms(*a, **k)
        return sw.adoption_verdict(full, ex, "CAND", required_starts=STARTS)

    def test_four_readings_pass(self):
        v, reasons, vals = self.verdict(main=0.01, cagr=0.01)
        self.assertEqual(v, "可采纳"); self.assertEqual(reasons, [])
        self.assertAlmostEqual(vals["主读数"][0], 0.01); self.assertEqual(len(vals["回撤段"]), 2)

    def test_drawdown_path_adopts(self):
        v, reasons, vals = self.verdict(main=-0.008, cagr=0.01, mdd=-0.08)
        self.assertEqual(v, "可采纳·回撤通道")
        self.assertIn("ΔMDD -8.0／-8.0pp", reasons[0]); self.assertIn("2015-06~2016-06×4 -8.0", reasons[0])
        self.assertEqual([ep["n"] for ep in vals["回撤段"]], [4, 4])   # 两表合并：每段 2 起点 × 2 表

    def test_drawdown_path_needs_five_pp_both_tables(self):
        self.assertEqual(self.verdict(main=-0.008, cagr=0.01, mdd=-0.04)[0], "不采纳")
        self.assertEqual(self.verdict(main=-0.008, cagr=0.01, mdd=-0.08, mdd_ex=-0.03)[0], "不采纳")   # 去赢家表未达 −5pp
        v, reasons, _ = self.verdict(main=-0.008, cagr=0.01, mdd=-0.08, worst=-0.01)
        self.assertEqual(v, "不采纳"); self.assertIn("回撤通道未过：滚5最差", "；".join(reasons))   # 回撤达标才解释为何没走通道

    def test_drawdown_path_needs_two_episodes(self):
        v, reasons, vals = self.verdict(main=-0.008, cagr=0.01, mdd=-0.16, mdd_starts=STARTS[:2])
        self.assertEqual(v, "不采纳")                       # 两表 ΔMDD 中位 −8pp 达标，但只有 2015 一段更浅
        self.assertIn("回撤段 1 < 2", "；".join(reasons))

    def test_drawdown_path_floors(self):
        self.assertEqual(self.verdict(main=-0.012, cagr=0.01, mdd=-0.08)[0], "不采纳")      # 主读数破 −1pp
        self.assertEqual(self.verdict(main=-0.008, cagr=-0.003, mdd=-0.08)[0], "不采纳")    # 复利劣于噪声带
        self.assertEqual(self.verdict(main=-0.008, cagr=0.01, mdd=-0.08, worst=-0.01)[0], "不采纳")  # 滚 5 最差变差

    def test_gate_overrides_drawdown_path(self):
        v, reasons, _ = self.verdict(main=-0.008, cagr=0.01, mdd=-0.08, r5dd=0.04)
        self.assertEqual(v, "不采纳"); self.assertTrue(any(r.startswith("闸门") for r in reasons))

    def test_ruling_band_still_reported(self):
        v, _, _ = self.verdict(main=-0.008, cagr=0.02, main_ex=0.02)
        self.assertEqual(v, "报用户裁定")
        v, _, _ = self.verdict(main=-0.008, cagr=0.02, main_ex=0.02, mdd=-0.08)
        self.assertEqual(v, "可采纳·回撤通道")

    def test_missing_window_series_is_undecidable(self):
        full, ex = arms(main=0.01, cagr=0.01)
        del full["CAND"][STARTS[0]][sw.WIN5_KEY]
        v, reasons, _ = sw.adoption_verdict(full, ex, "CAND", required_starts=STARTS)
        self.assertEqual(v, "不可判"); self.assertIn("缺同窗序列", reasons[0])
        # 历史 m2 文件核对：改用旧主读数键（不要求同窗序列），回撤通道可关
        full, ex = arms(main=-0.008, cagr=0.01, mdd=-0.08)
        for rows in (*full.values(), *ex.values()):
            for r in rows.values():
                del r[sw.WIN5_KEY]
        keys = (("主读数", "年化"), ("复利读数", "年化"))
        self.assertEqual(sw.adoption_verdict(full, ex, "CAND", verdict_keys=keys, required_starts=STARTS)[0], "可采纳")
        self.assertEqual(sw.adoption_verdict(full, ex, "CAND", verdict_keys=keys, dd_path=False, required_starts=STARTS)[0], "可采纳")

    # ---- OI-172：部分缺窗／缺起点／非有限值一律不可判（审核报告 P2 反例：BASE 三窗 10%，候选 20/−20/−50%）
    def test_partial_windows_cannot_pass(self):
        full, ex = arms(main=0.01, cagr=0.01)
        for s in STARTS:
            full["BASE"][s][sw.WIN5_KEY] = {m: 0.10 for m in WIN}
            full["CAND"][s][sw.WIN5_KEY] = {WIN[0]: 0.20, WIN[1]: -0.20, WIN[2]: -0.50}
        self.assertAlmostEqual(sw.start_delta(full["CAND"][STARTS[0]], full["BASE"][STARTS[0]], sw.WIN5_KEY), -0.30)
        for s in STARTS:                       # 候选只留第一个（有利）窗口：交集读 +10pp，严格口径必须 NaN
            full["CAND"][s][sw.WIN5_KEY] = {WIN[0]: 0.20}
        self.assertTrue(math.isnan(sw.start_delta(full["CAND"][STARTS[0]], full["BASE"][STARTS[0]], sw.WIN5_KEY)))
        self.assertAlmostEqual(sw.start_delta(full["CAND"][STARTS[0]], full["BASE"][STARTS[0]], sw.WIN5_KEY, coverage="common"), 0.10)
        v, reasons, _ = sw.adoption_verdict(full, ex, "CAND", required_starts=STARTS)
        self.assertEqual(v, "不可判"); self.assertTrue(any("窗口集合不同" in r for r in reasons))
        with self.assertRaises(ValueError):
            sw.start_delta(full["CAND"][STARTS[0]], full["BASE"][STARTS[0]], sw.WIN5_KEY, coverage="union")

    def test_missing_start_cannot_pass(self):
        full, ex = arms(main=0.01, cagr=0.01)
        del full["CAND"][STARTS[-1]]           # 候选少一个起点：交集给有限值，严格口径不可判
        self.assertTrue(math.isnan(sw._paired_median(full, "CAND", "年化")))
        self.assertFalse(math.isnan(sw._paired_median(full, "CAND", "年化", coverage="common")))
        v, reasons, _ = sw.adoption_verdict(full, ex, "CAND", required_starts=STARTS)
        self.assertEqual(v, "不可判"); self.assertTrue(any("缺起点" in r for r in reasons))
        full, ex = arms(main=0.01, cagr=0.01)   # 两臂起点齐但与标准起点集不符：同样不可判
        v, reasons, _ = sw.adoption_verdict(full, ex, "CAND", required_starts=(*STARTS, "2011-05-01"))
        self.assertEqual(v, "不可判"); self.assertTrue(any("缺起点 1/5" in r for r in reasons))

    def test_non_finite_values_cannot_pass(self):
        full, ex = arms(main=0.01, cagr=0.01)
        full["CAND"][STARTS[1]]["年化"] = float("nan")
        v, reasons, _ = sw.adoption_verdict(full, ex, "CAND", required_starts=STARTS)
        self.assertEqual(v, "不可判"); self.assertTrue(any("非有限值" in r for r in reasons))
        full, ex = arms(main=0.01, cagr=0.01)
        full["CAND"][STARTS[1]][sw.WIN5_KEY][WIN[1]] = float("inf")
        self.assertTrue(math.isnan(sw.start_delta(full["CAND"][STARTS[1]], full["BASE"][STARTS[1]], sw.WIN5_KEY)))
        self.assertEqual(sw.adoption_verdict(full, ex, "CAND", required_starts=STARTS)[0], "不可判")

    # ---- OI-173：否决只数「负窗占比由 0 转正」的起点，非零增大不计，恰好半数不否决
    def test_nonzero_increase_is_not_a_veto(self):
        full, ex = arms(main=0.01, cagr=0.01)
        for s in STARTS:                       # 双方本就有负窗：1% → 2%，四读数各 +1pp，不得否决
            full["BASE"][s]["滚动5年为负的窗口占比"] = 0.01
            full["CAND"][s]["滚动5年为负的窗口占比"] = 0.02
        v, reasons, _ = sw.adoption_verdict(full, ex, "CAND", required_starts=STARTS)
        self.assertEqual((v, reasons), ("可采纳", []))
        self.assertFalse(sw.neg_window_flip(full["CAND"][STARTS[0]], full["BASE"][STARTS[0]]))

    def test_zero_to_positive_over_half_vetoes(self):
        full, ex = arms(main=0.01, cagr=0.01)
        for s in STARTS[:3]:                   # 3/4 起点由 0 转正 → 否决
            full["CAND"][s]["滚动5年为负的窗口占比"] = 0.01
        v, reasons, _ = sw.adoption_verdict(full, ex, "CAND", required_starts=STARTS)
        self.assertEqual(v, "不采纳"); self.assertIn("否决：负窗 0→正 3/4", reasons)

    def test_exactly_half_is_not_over_half(self):
        full, ex = arms(main=0.01, cagr=0.01)
        for s in STARTS[:2]:                   # 2/4 不过半 → 不否决
            full["CAND"][s]["滚动5年为负的窗口占比"] = 0.01
        self.assertEqual(sw.adoption_verdict(full, ex, "CAND", required_starts=STARTS)[0], "可采纳")

    def test_dose_table_and_slippage_delegate(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent / "experimental"))
        import dose_table, oi148_slippage_report
        full, ex = arms(main=-0.008, cagr=0.01, mdd=-0.08)
        with mock.patch.object(sw, "DEFAULT_STARTS", list(STARTS)):     # 正式入口缺省按现行标准起点集校验完整性
            self.assertTrue(dose_table.verdict(full, ex, "CAND").startswith("可采纳·回撤通道"))
            self.assertEqual(oi148_slippage_report.verdict(full, ex, "CAND", "BASE")[0], "可采纳·回撤通道")
        self.assertEqual(dose_table.verdict(full, ex, "CAND")[:3], "不可判"[:3])                 # 4 个合成起点 ≠ 14 个标准起点


if __name__ == "__main__":
    unittest.main()
