"""§6.5.2.2 采用研究数：生产带的盈利锚换成研究数、投入资本不变，其余参数与股权桥照带。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_forecast_band_overlay as o  # noqa: E402
from intrinsic_value import intrinsic_value  # noqa: E402


def _band(**over) -> dict[str, str]:
    nopat, roic0, g0, wacc = 7.0896, 1.1182, 0.0, 0.0998
    ev = intrinsic_value(nopat, roic0, g0, wacc, roe_terminal=min(wacc + 0.02, roic0), g_terminal=0.03, **o.FADE).intrinsic_value
    band = dict(security_code="000858", roic_path="growth", status="ok", nopat_ps=str(nopat), roic0=str(roic0), g0=str(g0),
                wacc=str(wacc), g_terminal="0.03", shares_est="3881608005", fin_net_debt_ps="-32.0678",
                minority_book_ps="0.5732", minority_share="0.0416", external_equity_ps="0", ev_ps=f"{ev:.4f}")
    band.update(over)
    if band["ev_ps"]:
        iv = o.equity_from_ev(band, float(band["ev_ps"]), 0.0)
        band.setdefault("intrinsic_value", f"{iv:.4f}")
        band.setdefault("net_debt_ps", f"{float(band['ev_ps']) - iv:.4f}")
    return band


def _dossier(research: float) -> dict[str, str]:
    return dict(security_code="000858", research_nopat_yi=str(research), divergence_reviewed_at="2026-09-24",
                divergence_review_conclusion="采用研究数")


class ResearchOverlayTest(unittest.TestCase):
    def test_research_equal_to_model_leaves_value_unchanged(self) -> None:
        band = _band()
        old, new = o.apply_research_overlay(band, _dossier(7.0896 * 3881608005 / 1e8))
        self.assertAlmostEqual(new, old, places=3)
        self.assertEqual(band["model_nopat_ps"], "7.0896")

    def test_research_keeps_invested_capital_and_recomputes_the_bridge(self) -> None:
        band = _band()
        old, new = o.apply_research_overlay(band, _dossier(177.92))
        k = 177.92e8 / 3881608005 / 7.0896
        self.assertAlmostEqual(float(band["roic0"]), 1.1182 * k, places=3)
        nopat, roic0 = 7.0896 * k, 1.1182 * k
        ev = intrinsic_value(nopat, roic0, 0.0, 0.0998, roe_terminal=0.1198, g_terminal=0.03, **o.FADE).intrinsic_value
        self.assertAlmostEqual(float(band["ev_ps"]), ev, places=2)
        self.assertAlmostEqual(new, float(band["ev_ps"]) - float(band["net_debt_ps"]), places=3)
        self.assertAlmostEqual(float(band["band_low"]), 0.9 * new, places=3)
        self.assertEqual(band["research_overlay"], "2026-09-24")
        self.assertLess(new, old)

    def test_zero_growth_scales_ev_with_nopat(self) -> None:
        band = _band(roic_path="zero_growth", ev_ps="", intrinsic_value="60.0", net_debt_ps="-30.0")
        o.apply_research_overlay(band, _dossier(7.0896 * 3881608005 / 1e8 / 2))
        self.assertAlmostEqual(float(band["ev_ps"]), 15.0, places=3)

    def test_normalized_band_and_other_paths_are_refused(self) -> None:
        self.assertIsInstance(o.apply_research_overlay(_band(exright_note="除权归一化"), _dossier(177.92)), str)
        self.assertIsInstance(o.apply_research_overlay(_band(roic_path="bank_divspread"), _dossier(177.92)), str)


if __name__ == "__main__":
    unittest.main()
