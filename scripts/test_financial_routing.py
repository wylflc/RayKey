#!/usr/bin/env python3
"""OI-200／OI-203：类金融识别、客户资金不计现金、权益口径的 λ 锚与峰谷守卫、原文核定的重述前面板版本。"""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_historical_valuation_bands as bhvb  # noqa: E402
import restatement_archive  # noqa: E402
from roic_inputs import _year_from_parts  # noqa: E402

INCOME = {"NOTICE_DATE": "2026-03-20", "TOTAL_PROFIT": "140", "INCOME_TAX": "20", "TOTAL_OPERATE_INCOME": "160"}


def balance(**extra):
    row = {"NOTICE_DATE": "2026-03-20", "org_table": "RPT_F10_FINANCE_GBALANCE", "TOTAL_ASSETS": "3900",
           "TOTAL_EQUITY": "919", "TOTAL_PARENT_EQUITY": "919", "MONETARYFUNDS": "1243", "TRADE_FINASSET_NOTFVTPL": "1095"}
    row.update({k: str(v) for k, v in extra.items()})
    return row


class RoutingTest(unittest.TestCase):
    def year(self, **extra):
        return _year_from_parts("T", "2025-12-31", {"balance": balance(**extra), "income": INCOME}, False)

    def test_client_funds_leave_excess_cash(self):
        plain = self.year()
        broker = self.year(AGENT_TRADE_SECURITY=1411)
        self.assertAlmostEqual(plain.excess_cash - broker.excess_cash, 1411)
        self.assertEqual(broker.client_funds, 1411)

    def test_intermediation_share_of_assets_routes_to_equity(self):
        y = self.year(AGENT_TRADE_SECURITY=1411, SELL_REPO_FINASSET=400, BORROW_FUND=148)
        self.assertTrue(y.is_financial)
        self.assertEqual(y.financial_basis, "intermediation")

    def test_industrial_finance_subsidiary_stays_on_roic(self):
        # 茅台型：财务公司吸收关联方存款约占总资产 6%～9.5%
        y = self.year(ACCEPT_DEPOSIT_INTERBANK=300)
        self.assertFalse(y.is_financial)
        self.assertEqual(y.financial_basis, "")

    def test_template_financials_unchanged(self):
        y = _year_from_parts("T", "2025-12-31", {"balance": balance(org_table="RPT_F10_FINANCE_BBALANCE"),
                                                  "income": INCOME}, False)
        self.assertTrue(y.is_financial)
        self.assertEqual(y.financial_basis, "template")


def panel(roes: dict[int, float], quarter: tuple[str, float, float] | None = None) -> dict[str, dict]:
    """年报行 ROE（%）与归母净利；quarter = (期末, 本期累计净利, 上年同期累计净利)。"""
    series = {}
    for year, roe in roes.items():
        series[f"{year}-12-31"] = {"weightavg_roe": str(roe), "parent_netprofit": "100", "notice_date": f"{year + 1}-03-20"}
    if quarter:
        period, ytd, ytd_prev = quarter
        series[period] = {"weightavg_roe": "1", "parent_netprofit": str(ytd), "notice_date": f"{period[:4]}-08-20"}
        series[f"{int(period[:4]) - 1}{period[4:]}"] = {"weightavg_roe": "1", "parent_netprofit": str(ytd_prev),
                                                        "notice_date": f"{int(period[:4]) - 1}-08-20"}
    return series


ARGS = SimpleNamespace(roe_years=5, roic_peak_k=1.6, roic_peak_ramp=0.3, ttm_current="on", ttm_trust="off", ttm_trust_delta=0.02)


class GuardedEquityAnchorTest(unittest.TestCase):
    def test_steady_roe_is_its_own_anchor(self):
        series = panel({y: 15.0 for y in range(2016, 2026)})
        roe0, meta = bhvb.guarded_equity_roe(series, "2025-12-31", "2026-04-30", ARGS)
        self.assertAlmostEqual(roe0, 0.15)
        self.assertEqual((meta["peak_w"], meta["trough_w"]), (0.0, 0.0))

    def test_peak_blends_to_five_year_median(self):
        roes = {y: 6.0 for y in range(2011, 2020)} | {2020: 18.0}      # 当期 3× 十年中位
        roe0, meta = bhvb.guarded_equity_roe(panel(roes), "2020-12-31", "2021-04-30", ARGS)
        self.assertEqual(meta["peak_w"], 1.0)
        self.assertAlmostEqual(roe0, 0.06)                              # 五年中位

    def test_rising_trust_follows_current(self):
        roes = {2016: 10.0, 2017: 10.5, 2018: 11.0, 2019: 11.5, 2020: 12.0, 2021: 12.5, 2022: 13.0, 2023: 13.5,
                2024: 14.0, 2025: 15.0}
        roe0, meta = bhvb.guarded_equity_roe(panel(roes), "2025-12-31", "2026-04-30", ARGS)
        self.assertEqual(meta["trust"], 1.0)
        self.assertAlmostEqual(roe0, 0.15)                              # λ=1 采信当期，未触守卫

    def test_quarter_uses_ttm_current(self):
        roes = {y: 15.0 for y in range(2016, 2026)}
        series = panel(roes, ("2026-06-30", 70.0, 50.0))               # TTM 因子 = (100 + 70 − 50)/100 = 1.2
        roe0, meta = bhvb.guarded_equity_roe(series, "2026-06-30", "2026-08-20", ARGS)
        self.assertAlmostEqual(meta["ttm_factor"], 1.2)
        self.assertAlmostEqual(roe0, 0.15)                              # λ=0：三年中位，不采信当期


class FilingOriginalsTest(unittest.TestCase):
    def test_filing_version_precedes_restated_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "originals.csv"
            fields = ["security_code", "report_date", "notice_date", "parent_netprofit", "bps", "superseded_at", "original_url"]
            with ref.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(dict(security_code="999999", report_date="2025-03-31", notice_date="2025-04-26",
                                     parent_netprofit="148.6", bps="38.17", superseded_at="2026-04-30",
                                     original_url="http://example/original.pdf"))
            out = {"999999": {"2025-03-31": {"security_code": "999999", "report_date": "2025-03-31",
                                             "notice_date": "2025-04-26", "notice_date_raw": "2025-04-26",
                                             "parent_netprofit": "44.2", "bps": "35.48", "source": "vendor"}}}
            saved = restatement_archive.FILING_ORIGINALS
            restatement_archive.FILING_ORIGINALS = ref
            try:
                bhvb.attach_panel_versions(out, {"999999"}, notice_cap=True)
            finally:
                restatement_archive.FILING_ORIGINALS = saved
            series = out["999999"]
            self.assertEqual(bhvb.series_as_of(series, "2025-10-31")["2025-03-31"]["parent_netprofit"], "148.6")
            self.assertEqual(bhvb.series_as_of(series, "2026-04-30")["2025-03-31"]["parent_netprofit"], "44.2")
            self.assertTrue(bhvb.series_as_of(series, "2025-10-31")["2025-03-31"]["source"].startswith("filing"))

    def test_missing_superseded_at_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "bad.csv"
            ref.write_text("security_code,report_date,superseded_at,original_url\n999999,2025-03-31,,x\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                restatement_archive.load_filing_originals(ref)


if __name__ == "__main__":
    unittest.main()
