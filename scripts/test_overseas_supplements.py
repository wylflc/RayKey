#!/usr/bin/env python3
"""OI-216 海外取数修正的回归测试。

Run: ``python3 scripts/test_overseas_supplements.py``

锁住：SEC 流动证券的「流动债券 + 公允价值股权证券」组合候选及其对长期投资伞项的去重守卫；ifrs-full 长期借款与
应付公司债分列相加、有借款合计时只取合计；字段级补充表 `overseas_statement_supplements.csv` 的整表校验（fail closed）、
按公开日生效、港股经营溢利内金融资产收益剔除与权益法份额计入、TTM 三期合成、非流动金融资产整值替换与沿用；
港股 F10 分页带次序键且查重（京东 FY2023 漏行）。
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_overseas_statements as st  # noqa: E402

COLUMNS = st.SUPPLEMENT_COLUMNS
COMPANIES = {"00316": ("HK", "CNY"), "09618": ("HK", "CNY"), "TEST": ("HK", "CNY"), "UBER": ("US", ""), "TSM": ("US", "")}


def supplement_row(**kw) -> dict[str, str]:
    row = dict(market="HK", security_code="00316", security_name="东方海外国际", period="2025-12-31", period_kind="annual",
               field="ebit_financial_income_in_operating", value="2252828803", unit="CNY", original_value="320514000",
               original_unit="USD", fx_to_report="7.0288", evidence_date="2026-04-22",
               source_url="https://www1.hkexnews.hk/x.pdf", source_ref="note 7", note="")
    row.update({k: str(v) for k, v in kw.items()})
    return row


def write_csv(rows: list[dict], columns=COLUMNS) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="")
    with handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows([{k: r.get(k, "") for k in columns} for r in rows])
    return Path(handle.name)


class SecEquitySecuritiesTest(unittest.TestCase):
    def test_nvidia_custom_face_line_uses_debt_plus_equity(self):
        # FY2026 10-K 正表「Marketable securities」为自定义元素 51,951 = 流动债券 39,065 + 公允价值股权 12,886
        values = {"CashAndCashEquivalentsAtCarryingValue": 10605.0, "DebtSecuritiesCurrent": 39065.0,
                  "EquitySecuritiesFvNi": 12886.0, "EquitySecuritiesFVNINoncurrent": 22251.0, "Assets": 206803.0}
        fin = st.sec_financial_assets("us-gaap", values.get)
        self.assertEqual(fin["cash"], 10605.0 + 51951.0)
        self.assertEqual(fin["other"], 22251.0)
        self.assertEqual(fin["tags"]["securities_current"], "DebtSecuritiesCurrent+EquitySecuritiesFvNi")

    def test_face_total_already_containing_equity_is_kept(self):
        # Meta：MarketableSecuritiesCurrent 45,719 已含有价股权 5,992，无 DebtSecuritiesCurrent，不另加
        values = {"CashAndCashEquivalentsAtCarryingValue": 35873.0, "MarketableSecuritiesCurrent": 45719.0,
                  "EquitySecuritiesFvNi": 5992.0, "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount": 20076.0,
                  "EquityMethodInvestments": 7448.0}
        fin = st.sec_financial_assets("us-gaap", values.get)
        self.assertEqual((fin["cash"], fin["other"]), (35873.0 + 45719.0, 20076.0))
        self.assertEqual(fin["tags"]["securities_current"], "MarketableSecuritiesCurrent")

    def test_group_wins_when_composite_is_not_larger(self):
        values = {"ShortTermInvestments": 100.0, "DebtSecuritiesCurrent": 60.0, "EquitySecuritiesFvNi": 30.0,
                  "LongTermInvestments": 50.0}
        fin = st.sec_financial_assets("us-gaap", values.get)
        self.assertEqual((fin["cash"], fin["other"]), (100.0, 50.0))       # 伞项不扣股权证券

    def test_equity_inside_long_term_investments_is_not_counted_twice(self):
        # eBay 2021-06-30：公允价值股权（Adevinta 等）在「Long-term investments」伞项内；组合候选选中后伞项须扣除
        values = {"CashAndCashEquivalentsAtCarryingValue": 2000.0, "DebtSecuritiesCurrent": 4738.0,
                  "EquitySecuritiesFvNi": 10354.0, "LongTermInvestments": 12000.0,
                  "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount": 300.0}
        fin = st.sec_financial_assets("us-gaap", values.get)
        self.assertEqual(fin["cash"], 2000.0 + 4738.0 + 10354.0)
        self.assertEqual(fin["other"], 12000.0 - 10354.0)
        self.assertEqual(fin["cash"] + fin["other"], 2000.0 + 4738.0 + 12000.0)   # 股权证券只计一次

    def test_composite_concepts_are_extracted_for_annual_rows(self):
        self.assertIn("EquitySecuritiesFvNi", st.SEC_FIN_CONCEPTS)
        self.assertIn("DebtSecuritiesCurrent", st.SEC_FIN_CONCEPTS)


class IfrsDebtTest(unittest.TestCase):
    @staticmethod
    def getter(values):
        return lambda k: values.get(k)

    def test_bank_loans_and_bonds_are_summed(self):
        # 台积电 2024：长期银行借款 31,824.4 + 应付公司债 926,604.5 + 一年内到期 59,857.9
        value, parts = st.compose_debt(self.getter({"lt_loans_noncurrent": 31824.4, "bonds_noncurrent": 926604.5,
                                                    "lt_debt_current": 59857.9}))
        self.assertAlmostEqual(value, 31824.4 + 926604.5 + 59857.9)
        self.assertEqual(parts, ("lt_loans_noncurrent", "bonds_noncurrent", "lt_debt_current"))

    def test_combined_total_is_not_added_to_components(self):
        value, parts = st.compose_debt(self.getter({"lt_debt_noncurrent": 900.0, "lt_loans_noncurrent": 100.0,
                                                    "bonds_noncurrent": 800.0, "lt_debt_current": 50.0}))
        self.assertEqual((value, parts), (950.0, ("lt_debt_noncurrent", "lt_debt_current")))

    def test_bonds_alone(self):
        value, parts = st.compose_debt(self.getter({"bonds_noncurrent": 25.1, "lt_debt_current": 31.8, "st_debt": 118.5}))
        self.assertAlmostEqual(value, 25.1 + 31.8 + 118.5)
        self.assertEqual(parts, ("bonds_noncurrent", "lt_debt_current", "st_debt"))

    def test_ifrs_statement_row_sums_bonds_and_loans(self):
        def instant(val):
            return {"units": {"TWD": [dict(end="2024-12-31", filed="2025-04-17", fp="FY", form="20-F", val=val)]}}

        def duration(val):
            return {"units": {"TWD": [dict(start="2024-01-01", end="2024-12-31", filed="2025-04-17", fp="FY", form="20-F", val=val)]}}
        facts = {"Revenue": duration(2894307.7), "ProfitLossBeforeTax": duration(1405840.0),
                 "ProfitLossFromOperatingActivities": duration(1322053.0),
                 "LongtermBorrowings": instant(31824.4), "NoncurrentPortionOfNoncurrentBondsIssued": instant(926604.5),
                 "CurrentPortionOfLongtermBorrowings": instant(59857.9)}
        row = st.sec_extract("TSMX", "测试", {"facts": {"ifrs-full": facts}})[0]
        self.assertAlmostEqual(row["interest_debt"], 31824.4 + 926604.5 + 59857.9)
        self.assertIn("interest_debt=LongtermBorrowings+NoncurrentPortionOfNoncurrentBondsIssued+CurrentPortionOfLongtermBorrowings",
                      row["tags_used"])


class SupplementLoaderTest(unittest.TestCase):
    def load(self, rows, as_of="2026-09-28", columns=COLUMNS):
        path = write_csv(rows, columns)
        self.addCleanup(path.unlink)
        return st.load_statement_supplements(as_of, COMPANIES, path)

    def test_valid_rows_and_evidence_date_gate(self):
        rows = [supplement_row(),
                supplement_row(period="2026-06-30", period_kind="interim_ytd", value="833599673", evidence_date="2026-08-27")]
        out = self.load(rows, as_of="2026-08-26")
        self.assertEqual(set(out["00316"]["ebit_financial_income_in_operating"]), {"2025-12-31"})   # 未到公开日不生效
        out = self.load(rows)
        item = out["00316"]["ebit_financial_income_in_operating"]["2026-06-30"]
        self.assertEqual((item["value"], item["period_kind"], item["_used"]), (833599673.0, "interim_ytd", False))

    def test_fail_closed_cases(self):
        cases = {
            "unknown field": [supplement_row(field="cash_like")],
            "unknown company": [supplement_row(security_code="99999")],
            "market mismatch": [supplement_row(market="US")],
            "field not for market": [supplement_row(market="US", security_code="UBER", unit="USD")],
            "bad period kind": [supplement_row(period_kind="balance")],
            "missing evidence date": [supplement_row(evidence_date="")],
            "missing source": [supplement_row(source_url="")],
            "missing source ref": [supplement_row(source_ref=" ")],
            "evidence before period end": [supplement_row(evidence_date="2025-12-30")],
            "bad period": [supplement_row(period="2025-13-31")],
            "non numeric value": [supplement_row(value="n/a")],
            "nan value": [supplement_row(value="nan")],
            "unit mismatch": [supplement_row(unit="USD")],
            "duplicate key": [supplement_row(), supplement_row(value="1")],
        }
        for name, rows in cases.items():
            with self.subTest(name), self.assertRaises(st.SupplementError):
                self.load(rows)
        with self.assertRaises(st.SupplementError):
            self.load([supplement_row()], columns=[c for c in COLUMNS if c != "evidence_date"])

    def test_missing_file_means_no_supplements(self):
        self.assertEqual(st.load_statement_supplements("2026-09-28", COMPANIES, Path("/nonexistent/x.csv")), {})


def hk_tables(period: str, income: dict[str, float], date_type: str = "001") -> dict[str, list[dict]]:
    def rows(items):
        return [{"REPORT_DATE": f"{period} 00:00:00", "DATE_TYPE_CODE": date_type, "STD_ITEM_NAME": n, "AMOUNT": a}
                for n, a in items.items()]
    balance = {"总权益": 900.0, "股东权益": 880.0, "少数股东权益": 20.0, "现金及等价物": 300.0, "总资产": 2000.0}
    return {"balance": rows(balance), "income": rows(income), "cashflow": rows({"经营业务现金净额": 220.0})}


def merged(*tables):
    return {kind: [r for t in tables for r in t[kind]] for kind in ("balance", "income", "cashflow")}


class HkSupplementTest(unittest.TestCase):
    INCOME = {"营业额": 1000.0, "经营溢利": 200.0, "除税前溢利": 190.0, "税项": 30.0, "融资成本": 10.0,
              "其他收入": 40.0, "其他收益": 5.0, "股东应占溢利": 150.0}

    def supplements(self, rows):
        path = write_csv(rows)
        self.addCleanup(path.unlink)
        return st.load_statement_supplements("2026-09-28", COMPANIES, path)["TEST"]

    def test_hong_kong_ebit_removes_financial_income_inside_operating_profit(self):
        parts = {"operating_income": 10.79, "investment_gains": 0.36, "equity_method_income": 0.09, "financial_income_in_op": 2.25}
        self.assertAlmostEqual(st.hk_ebit(parts.get)[0], 10.79 - 0.36 - 2.25 + 0.09)
        parts = {"pretax": 51.6, "interest_expense": 2.0, "investment_gains": 3.6, "financial_income_in_op": 2.6}
        self.assertEqual(st.hk_ebit(parts.get), (51.6 + 2.0 - 2.6 - 3.6, "pretax_strip"))
        parts["interest_income"] = 1.0                                         # F10 有利息收入行时以其为准
        self.assertEqual(st.hk_ebit(parts.get), (51.6 + 2.0 - 1.0 - 3.6, "pretax_strip"))

    def test_annual_row_uses_supplements(self):
        supp = self.supplements([
            supplement_row(security_code="TEST", security_name="测试", value="30"),
            supplement_row(security_code="TEST", security_name="测试", field="equity_method_income", value="12")])
        row = st.hk_extract("TEST", "测试", hk_tables("2025-12-31", self.INCOME), 10.0, supplements=supp)[0]
        self.assertAlmostEqual(row["ebit"], 200.0 - 5.0 - 30.0 + 12.0)
        self.assertEqual((row["financial_income_in_op"], row["equity_method_income"]), (30.0, 12.0))
        self.assertIn(f"financial_income_in_op={st.SUPPLEMENT_TAG}", row["tags_used"])
        self.assertTrue(all(item["_used"] for items in supp.values() for item in items.values()))
        plain = st.hk_extract("TEST", "测试", hk_tables("2025-12-31", self.INCOME), 10.0)[0]
        self.assertAlmostEqual(plain["ebit"], 195.0)
        self.assertNotIn("supplement", plain["tags_used"])

    def test_equity_supplement_conflicts_with_f10_line(self):
        supp = self.supplements([supplement_row(security_code="TEST", security_name="测试", field="equity_method_income",
                                                value="12")])
        income = dict(self.INCOME, 应占联营公司溢利=3.0)
        with self.assertRaises(st.SupplementError):
            st.hk_extract("TEST", "测试", hk_tables("2025-12-31", income), 10.0, supplements=supp)

    def test_ttm_combines_three_periods_and_fails_closed(self):
        tables = merged(hk_tables("2025-12-31", self.INCOME), hk_tables("2026-06-30", self.INCOME, "002"),
                        hk_tables("2025-06-30", self.INCOME, "002"))
        rows = [supplement_row(security_code="TEST", security_name="测试", value="30"),
                supplement_row(security_code="TEST", security_name="测试", period="2026-06-30", period_kind="interim_ytd",
                               value="14", evidence_date="2026-08-27"),
                supplement_row(security_code="TEST", security_name="测试", period="2025-06-30", period_kind="interim_ytd",
                               value="20", evidence_date="2026-08-27")]
        supp = self.supplements(rows)
        annual = st.hk_extract("TEST", "测试", tables, 10.0, supplements=supp)
        row = st.hk_current_extract("TEST", "测试", tables, 10.0, annual, evidence_date="2026-08-27", supplements=supp,
                                    report_period="2026-06-30")
        self.assertAlmostEqual(row["financial_income_in_op"], 30.0 + 14.0 - 20.0)
        self.assertAlmostEqual(row["ebit"], (200.0 - 5.0) - (30.0 + 14.0 - 20.0))
        # 证据未登记的新一期：不取补充值、不校验
        other = st.hk_current_extract("TEST", "测试", tables, 10.0, annual, evidence_date="2026-08-27",
                                      supplements=self.supplements(rows[:1]), report_period="2025-12-31")
        self.assertAlmostEqual(other["ebit"], 195.0)
        with self.assertRaises(st.SupplementError):                            # 缺上年同期
            st.hk_current_extract("TEST", "测试", tables, 10.0, annual, evidence_date="2026-08-27",
                                  supplements=self.supplements(rows[:2]), report_period="2026-06-30")
        with self.assertRaises(st.SupplementError):                            # 年报期类别错用
            st.supplement_value("TEST", supp, "ebit_financial_income_in_operating", "2026-06-30", "annual")


class BalanceSupplementTest(unittest.TestCase):
    @staticmethod
    def row(period="2025-12-31", period_type="annual", other=4397.0, ccy="USD"):
        row = st._build_row("US", "UBER", "优步", period, period, ccy, 52017.0, 5565.0, 5800.0, 0.0, 440.0,
                            27918.0, 27041.0, 877.0, 10743.0, 10175.0, 0, 0, 0, 2000.0, {}, "test", 0.21,
                            ebit=5512.0, ebit_source="operating", financial=dict(other=other), period_type=period_type)
        return row

    def supplements(self, rows):
        path = write_csv(rows)
        self.addCleanup(path.unlink)
        return st.load_statement_supplements("2026-09-28", COMPANIES, path).get("UBER")

    @staticmethod
    def uber(period, value, evidence):
        return supplement_row(market="US", security_code="UBER", security_name="优步", period=period, period_kind="balance",
                              field="other_financial_assets", value=value, unit="USD", evidence_date=evidence)

    def test_replace_and_recompute(self):
        supp = self.supplements([self.uber("2025-12-31", 9178.0, "2026-02-13")])
        row = self.row()
        before_excess = row["excess_cash"]
        self.assertEqual(st.apply_balance_supplements([row], supp), 1)
        self.assertEqual(row["other_financial_assets"], 9178.0)
        self.assertAlmostEqual(row["excess_cash"], before_excess - 4397.0 + 9178.0)
        self.assertAlmostEqual(row["invested_capital"], max(10743.0 + 27918.0 - row["excess_cash"], st.IC_FLOOR * 27918.0))
        self.assertIn("other_financial_assets=supplement:2025-12-31", row["tags_used"])
        self.assertEqual(st.unused_supplements({"UBER": supp}), [])

    def test_ttm_carry_within_fifteen_months_only(self):
        supp = self.supplements([self.uber("2025-12-31", 9178.0, "2026-02-13")])
        ttm = self.row(period="2026-06-30", period_type="ttm", other=3812.0)
        st.apply_balance_supplements([ttm], supp)
        self.assertEqual(ttm["other_financial_assets"], 9178.0)
        self.assertIn("other_financial_assets=supplement_carried:2025-12-31", ttm["tags_used"])
        stale = self.row(period="2027-06-30", period_type="ttm", other=3812.0)
        self.assertEqual(st.apply_balance_supplements([stale], supp), 0)
        self.assertEqual(stale["other_financial_assets"], 3812.0)
        annual_without = self.row(period="2024-12-31", other=3199.0)          # 年报行不沿用
        self.assertEqual(st.apply_balance_supplements([annual_without], supp), 0)

    def test_unit_must_match_report_currency(self):
        supp = self.supplements([self.uber("2025-12-31", 9178.0, "2026-02-13")])
        with self.assertRaises(st.SupplementError):
            st.apply_balance_supplements([self.row(ccy="TWD")], supp)

    def test_unused_rows_are_listed(self):
        supp = self.supplements([self.uber("2025-12-30", 9178.0, "2026-02-13")])
        st.apply_balance_supplements([self.row()], supp)
        self.assertEqual(st.unused_supplements({"UBER": supp}), ["UBER other_financial_assets 2025-12-30"])


class HkDownloadPagingTest(unittest.TestCase):
    """京东 FY2023：只按 REPORT_DATE 排序时跨页重复／漏行；须带 STD_ITEM_CODE 次序键，且下载结果查重。"""

    @staticmethod
    def page(rows, pages):
        return json.dumps({"result": {"pages": pages, "data": rows}}).encode("utf-8")

    def run_download(self, pages_payload, cached=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raw = Path(tmp.name)
        if cached is not None:
            (raw / "hk").mkdir(parents=True)
            for kind in ("balance", "income", "cashflow"):
                (raw / "hk" / f"TEST_{kind}.json").write_text(json.dumps(cached), encoding="utf-8")
        urls = []

        def fake_get(url, headers, timeout=40):
            urls.append(url)
            return pages_payload[(len(urls) - 1) % len(pages_payload)]
        with mock.patch.object(st, "RAW_DIR", raw), mock.patch.object(st, "_get", fake_get), \
                mock.patch.object(st.time, "sleep", lambda *_: None), mock.patch("builtins.print"):
            out = st.hk_download("TEST", refresh=True)
        return out, urls

    def test_stable_secondary_sort_key(self):
        row = {"REPORT_DATE": "2023-12-31 00:00:00", "DATE_TYPE_CODE": "001", "STD_ITEM_CODE": "004002010", "AMOUNT": 1}
        out, urls = self.run_download([self.page([row], 1)])
        self.assertTrue(all("sortColumns=REPORT_DATE,STD_ITEM_CODE&sortTypes=-1,1" in u for u in urls))
        self.assertEqual(out["balance"], [row])

    def test_duplicate_rows_across_pages_keep_previous_cache(self):
        row = {"REPORT_DATE": "2023-12-31 00:00:00", "DATE_TYPE_CODE": "001", "STD_ITEM_CODE": "004002010", "AMOUNT": 1}
        cached = [dict(row, STD_ITEM_CODE=f"C{i}") for i in range(80)]           # > 1000 字节才被视为有效旧缓存
        out, _ = self.run_download([self.page([row], 2), self.page([row], 2)], cached=cached)
        self.assertEqual(out["balance"], cached)


class RepositoryTableTest(unittest.TestCase):
    def test_repository_supplement_table_is_valid(self):
        with st.WATCHLIST.open(encoding="utf-8-sig") as handle:
            watch = list(csv.DictReader(handle))
        companies = {r["security_code"]: (r["market_type"].upper(),
                                          st.HK_REPORT_CCY.get(r["security_code"], "CNY") if r["market_type"].upper() == "HK" else "")
                     for r in watch}
        out = st.load_statement_supplements("9999-12-31", companies)
        self.assertEqual(set(out), {"00316", "06862", "09618", "UBER", "TSM"})


if __name__ == "__main__":
    unittest.main()
