#!/usr/bin/env python3
"""§7.1 更新队列的时点隔离与信号日→证据日映射。"""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_report_update_queue as q


def _tier(code: str) -> dict[str, str]:
    return {"security_code": code, "security_name": f"N{code}", "quality_tier": "L2",
            "reviewed_at_utc": "2026-08-01T00:00:00Z", "evidence_available_at": ""}


def _pool(code: str, reviewed: str) -> dict[str, str]:
    return {"security_code": code, "valuation_reviewed_at": reviewed, "evidence_available_at": reviewed}


class ReportUpdateQueueAsOfTest(unittest.TestCase):
    def test_signal_date_automatically_exposes_next_workday_notice(self) -> None:
        disclosures = [
            {"security_code": "000651", "disclosure_type": "periodic_report",
             "notice_date": "2026-08-27", "report_date": "2026-06-30", "report_label": "2026 中报"},
        ]
        rows = q.build_queue_for_signal(
            [], [_tier("000651")], [_pool("000651", "2026-04-29")], [], [], disclosures, "2026-08-26"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["as_of"], "2026-08-27")
        self.assertEqual(rows[0]["latest_periodic_notice_date"], "2026-08-27")

    def test_future_dated_notice_is_invisible(self) -> None:
        disclosures = [
            {"security_code": "000001", "disclosure_type": "periodic_report",
             "notice_date": "2026-08-25", "report_date": "2026-06-30", "report_label": "2026 中报"},
        ]
        rows = q.build_queue([], [_tier("000001")], [_pool("000001", "2026-08-20")], [], [], disclosures, "2026-08-24")
        self.assertEqual(rows, [])
        rows = q.build_queue([], [_tier("000001")], [_pool("000001", "2026-08-20")], [], [], disclosures, "2026-08-25")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["latest_periodic_notice_date"], "2026-08-25")
        self.assertEqual(rows[0]["buy_blocked"], "review_pending")

    def test_earlier_visible_row_still_used_when_latest_is_future(self) -> None:
        disclosures = [
            {"security_code": "000002", "disclosure_type": "express_report",
             "notice_date": "2026-08-25", "report_date": "2026-06-30", "report_label": "快报"},
            {"security_code": "000002", "disclosure_type": "express_report",
             "notice_date": "2026-08-22", "report_date": "2026-06-30", "report_label": "快报"},
        ]
        rows = q.build_queue([], [_tier("000002")], [_pool("000002", "2026-08-20")], [], [], disclosures, "2026-08-24")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["latest_express_notice_date"], "2026-08-22")

    def test_forecast_respects_as_of(self) -> None:
        forecasts = [
            {"security_code": "000003", "is_latest": "T", "notice_date": "2026-08-25", "predict_type": "预增"},
        ]
        rows = q.build_queue([], [_tier("000003")], [_pool("000003", "2026-08-20")], [], forecasts, [], "2026-08-24")
        self.assertEqual(rows, [])
        rows = q.build_queue([], [_tier("000003")], [_pool("000003", "2026-08-20")], [], forecasts, [], "2026-08-25")
        self.assertEqual(len(rows), 1)
        self.assertIn("forecast_after_last_valuation_review", str(rows[0]["queue_reasons"]))

    def test_blank_notice_date_is_invisible(self) -> None:
        disclosures = [
            {"security_code": "000004", "disclosure_type": "periodic_report",
             "notice_date": "", "report_date": "2026-06-30", "report_label": "2026 中报"},
        ]
        rows = q.build_queue([], [_tier("000004")], [_pool("000004", "2026-08-20")], [], [], disclosures, "2026-08-24")
        self.assertEqual(rows, [])



def _band(code: str, nopat_ps: float, path: str = "growth") -> dict[str, str]:
    return {"security_code": code, "roic_path": path, "nopat_ps": str(nopat_ps), "shares_est": "1e9"}   # 锚 = nopat_ps × 10 亿元


def _dossier(code: str, research: float, **review) -> dict[str, str]:
    return {"security_code": code, "research_nopat_yi": str(research), **{k: str(v) for k, v in review.items()}}


class ResearchDivergenceTest(unittest.TestCase):
    """§7.3（OI-209）：研究正常化盈利与模型盈利锚差距超过 30% 入队，研究数低于模型锚时冻结；复核记录解除，任一数变动超过 10% 重新入队。"""

    def queue(self, dossier, band, tier=None, annual_notice=None):
        return q.build_queue([], [tier or _tier("000858")], [_pool("000858", "2026-09-01")], [], [], [], "2026-09-24",
                             [dossier], [band], {"000858": annual_notice} if annual_notice else None)

    def test_gap_above_threshold_blocks_buying(self) -> None:
        rows = self.queue(_dossier("000858", 186.5), _band("000858", 27.52))      # 275.2 ÷ 186.5 − 1 = 48%
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["buy_blocked"], "review_pending")
        self.assertIn("research_model_divergence", rows[0]["queue_reasons"])
        self.assertEqual(rows[0]["research_model_gap"], f"{275.2 / 186.5 - 1:.4f}")

    def test_research_above_model_is_queued_without_freeze(self) -> None:
        rows = self.queue(_dossier("000858", 247.0), _band("000858", 16.14))       # 247 ÷ 161.4 − 1 = 53%，研究数较高
        self.assertEqual(len(rows), 1)
        self.assertIn("research_model_divergence", rows[0]["queue_reasons"])
        self.assertTrue(rows[0]["valuation_review_needed"])
        self.assertEqual(rows[0]["buy_blocked"], "")

    def test_parent_profit_converts_through_the_equity_bridge(self) -> None:
        # 天齐锂业：62.5 ÷ (1 − 0.4701) + (29.0 − 30.0) = 116.9；五粮液：190 ÷ (1 − 0.0416) − 20.3 = 177.9
        self.assertAlmostEqual(q.research_nopat_from_parent(62.5, 0.4701, 29.0, 30.0), 116.95, places=2)
        self.assertAlmostEqual(q.research_nopat_from_parent(190.0, 0.0416, 72.8, 93.1), 177.95, places=2)
        self.assertAlmostEqual(q.research_nopat_from_parent(10.0, 1.2, 0.0, 0.0), 200.0)             # 份额封顶 0.95

    def test_gap_at_or_below_threshold_is_not_queued(self) -> None:
        self.assertEqual(self.queue(_dossier("000858", 100.0), _band("000858", 13.0)), [])   # 30% 整不入队
        self.assertEqual(self.queue(_dossier("000858", 100.0), _band("000858", 7.7)), [])    # 100 ÷ 77 − 1 < 30%

    def test_review_clears_until_either_figure_moves_ten_percent(self) -> None:
        reviewed = dict(divergence_reviewed_at="2026-09-20", divergence_reviewed_model_yi=275.2,
                        divergence_reviewed_research_yi=186.5)
        self.assertEqual(self.queue(_dossier("000858", 186.5, **reviewed), _band("000858", 29.0)), [])   # 模型 +5%
        self.assertEqual(len(self.queue(_dossier("000858", 186.5, **reviewed), _band("000858", 31.0))), 1)   # 模型 +12.6%
        self.assertEqual(len(self.queue(_dossier("000858", 160.0, **reviewed), _band("000858", 27.52))), 1)  # 研究 −14%

    def test_adopted_research_reads_the_mechanical_anchor(self) -> None:
        adopted = dict(divergence_reviewed_at="2026-09-24", divergence_review_conclusion="采用研究数",
                       divergence_reviewed_model_yi=275.2, divergence_reviewed_research_yi=177.9)
        band = dict(_band("000858", 17.79), research_overlay="2026-09-24", model_nopat_ps="27.52")   # 生产带已换成研究数
        self.assertEqual(self.queue(_dossier("000858", 177.9, **adopted), band), [])
        div = q.research_divergence(_dossier("000858", 177.9, **adopted), band)
        self.assertAlmostEqual(div["model"], 275.2)
        self.assertTrue(div["adopted"])

    def test_adopted_research_requeues_on_any_ten_percent_move_or_new_annual_report(self) -> None:
        adopted = dict(divergence_reviewed_at="2026-09-24", divergence_review_conclusion="采用研究数",
                       divergence_reviewed_model_yi=275.2, divergence_reviewed_research_yi=177.9)
        dossier = _dossier("000858", 177.9, **adopted)
        band = lambda model_ps: dict(_band("000858", 17.79), research_overlay="2026-09-24", model_nopat_ps=str(model_ps))
        rows = self.queue(dossier, band(21.0))              # 模型锚降到 210 亿：差距 18% 不超过 30%，但较复核时 −24%
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["buy_blocked"], "")         # 生产用研究数、研究数较低：只入队
        self.assertEqual(self.queue(dossier, band(27.52), annual_notice="2026-09-24"), [])
        self.assertEqual(len(self.queue(dossier, band(27.52), annual_notice="2027-04-28")), 1)   # 复核后公告新年报

    def test_adopted_research_freezes_when_research_is_the_higher_anchor(self) -> None:
        adopted = dict(divergence_reviewed_at="2026-09-24", divergence_review_conclusion="采用研究数",
                       divergence_reviewed_model_yi=161.4, divergence_reviewed_research_yi=232.3)
        band = dict(_band("000858", 23.23), research_overlay="2026-09-24", model_nopat_ps="14.0")    # 模型锚 −13%
        rows = self.queue(_dossier("000858", 232.3, **adopted), band)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["buy_blocked"], "review_pending")

    def test_non_roic_path_and_out_of_scope_are_skipped(self) -> None:
        self.assertEqual(self.queue(_dossier("000858", 50.0), _band("000858", 27.52, "equity_fallback")), [])
        tier = dict(_tier("000858"), quality_tier="L4")
        self.assertEqual(self.queue(_dossier("000858", 50.0), _band("000858", 27.52), tier), [])
        self.assertEqual(q.build_queue([], [_tier("000858")], [_pool("000858", "2026-09-01")], [], [], [], "2026-09-24"), [])

class StructuralGrowthReviewTest(unittest.TestCase):
    """§7.3 结构性增长复核（OI-249）：量驱动且峰守卫砍掉每股 NOPAT ≥ 40% 的入队、不冻结；登记研究数后转由差距规则管理。"""

    def queue(self, flagged=True, dossier=None, tier=None):
        growth = [{"security_code": "300308", "flagged": str(flagged), "cut": "0.5340"}]
        return q.build_queue([], [tier or _tier("300308")], [_pool("300308", "2026-09-01")], [], [], [], "2026-09-24",
                             [dossier] if dossier else [], [], None, growth)

    def test_flagged_company_is_queued_without_freeze(self) -> None:
        rows = self.queue()
        self.assertEqual(len(rows), 1)
        self.assertIn("structural_growth_review", rows[0]["queue_reasons"])
        self.assertEqual(rows[0]["buy_blocked"], "")
        self.assertTrue(rows[0]["valuation_review_needed"])
        self.assertEqual(rows[0]["structural_growth_cut"], "0.5340")

    def test_registered_research_hands_over_to_divergence_rule(self) -> None:
        rows = self.queue(dossier=_dossier("300308", 60.0))
        self.assertTrue(all("structural_growth_review" not in r["queue_reasons"] for r in rows))

    def test_unflagged_or_out_of_scope_is_skipped(self) -> None:
        self.assertEqual(self.queue(flagged=False), [])
        self.assertEqual(self.queue(tier=dict(_tier("300308"), quality_tier="L4")), [])


if __name__ == "__main__":
    unittest.main()
