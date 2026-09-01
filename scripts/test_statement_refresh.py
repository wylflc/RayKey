#!/usr/bin/env python3
"""三大报表增量取数的回归测试（OI-098）。

Run: ``python3 scripts/test_statement_refresh.py``

锁定的行为：`fetch_a_share_financial_statements.py` 按信号日推导证据日，并据此判应到年报期，
最新年报期落后的代码**整只重取并替换**、重取失败保留原有行。
2026-08-24 前的实现只看「代码是否已在文件里」，年报披露后按 §6.7 命令跑永远不更新已有代码。

**追溯重述探针（OI-126）**：已到期的代码不再跳过——重取资产负债表比 `UPDATE_DATE`，远端更新即三张表整只
重取替换，未变则本地行一字不动；探针取不到保留本地、不算失败；关键值实变写重述日志。
`--no-probe` 回到「已到期即跳过」。

无网络：`fetch` 被替换成内存桩，直接驱动 `main()` 走完整的读-合并-写路径。
"""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_a_share_financial_statements as fs  # noqa: E402

FIELDS = ["SECUCODE", "REPORT_DATE", "NOTICE_DATE", "UPDATE_DATE", "TOTAL_ASSETS", "TOTAL_PARENT_EQUITY",
          "security_code", "org_table", "source", "retrieved_at_utc"]


def _row(code: str, period: str, value: str = "1", update: str = "", equity: str = "100") -> dict:
    return {"SECUCODE": fs.secucode(code), "REPORT_DATE": period,
            "NOTICE_DATE": f"{int(period[:4]) + 1}-04-20", "UPDATE_DATE": update or f"{int(period[:4]) + 1}-04-20",
            "TOTAL_ASSETS": value, "TOTAL_PARENT_EQUITY": equity,
            "security_code": code, "org_table": "RPT_F10_FINANCE_GBALANCE",
            "source": "eastmoney RPT_F10_FINANCE_GBALANCE", "retrieved_at_utc": "2026-08-16T00:00:00+00:00"}


def _write(out_dir: Path, rows: list[dict]) -> None:
    for kind in fs.STATEMENTS:
        with (out_dir / f"{kind}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, restval="")
            writer.writeheader()
            writer.writerows(rows)


def _read(out_dir: Path, kind: str = "balance") -> list[dict]:
    with (out_dir / f"{kind}.csv").open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _api_rows(periods: list[str], code: str = "000001", update: dict | None = None,
              equity: str = "100") -> list[dict]:
    """东财原始行形态（日期带时间、无 security_code）。`update`：{期: UPDATE_DATE}，缺省＝下年 4-20（与本地相同）。"""
    return [{"SECUCODE": fs.secucode(code), "REPORT_DATE": f"{p} 00:00:00",
             "NOTICE_DATE": f"{int(p[:4]) + 1}-03-28 00:00:00",
             "UPDATE_DATE": f"{(update or {}).get(p, f'{int(p[:4]) + 1}-04-20')} 00:00:00",
             "TOTAL_ASSETS": "9", "TOTAL_PARENT_EQUITY": equity,
             "TOTAL_ASSETS_YOY": "0.1"} for p in periods]


class PlanTest(unittest.TestCase):
    def test_secucode_exchange_suffix(self):
        self.assertEqual(fs.secucode("600519"), "600519.SH")
        self.assertEqual(fs.secucode("000001"), "000001.SZ")
        self.assertEqual(fs.secucode("300750"), "300750.SZ")
        self.assertEqual(fs.secucode("920394"), "920394.BJ")   # 北交所 920 段，东财 F10 不认 .SH
        self.assertEqual(fs.secucode("430047"), "430047.BJ")
        self.assertEqual(fs.secucode("900901"), "900901.SH")   # 沪市 B 股

    def test_expected_period_is_previous_year_end(self):
        self.assertEqual(fs.expected_annual_period(date(2026, 8, 24)), "2025-12-31")
        self.assertEqual(fs.expected_annual_period(date(2027, 1, 1)), "2026-12-31")
        self.assertEqual(fs.expected_annual_period(date(2026, 12, 31)), "2025-12-31")

    def test_plan_splits_missing_and_stale(self):
        rows = [_row("600519", "2025-12-31"), _row("600519", "2024-12-31"),
                _row("000001", "2024-12-31")]
        missing, stale = fs.plan_codes(rows, ["000001", "600519", "601166"], "2025-12-31")
        self.assertEqual(missing, ["601166"])
        self.assertEqual(stale, ["000001"])
        missing, stale = fs.plan_codes(rows, ["000001", "600519"], "2026-12-31")
        self.assertEqual((missing, stale), ([], ["000001", "600519"]))


class MainMergeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        _write(self.out, [_row("600519", "2025-12-31", "A25"), _row("600519", "2024-12-31", "A24"),
                          _row("000001", "2024-12-31", "B24"), _row("000001", "2023-12-31", "B23")])
        self.calls: list[tuple[str, str]] = []

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, as_of: str, fetch_stub, probe: bool = False, min_years: int = 1,
             codes: list[str] | None = None) -> int:
        """`min_years` 缺省 1：夹具只有 2~3 个财年，生产阈值 3 会把每个用例都判成覆盖缺口。"""
        argv = ["prog", "--codes", *(codes or ["000001", "600519"]), "--out-dir", str(self.out),
                "--signal-date", as_of, "--pause", "0"] + ([] if probe else ["--no-probe"])
        with mock.patch.object(fs, "fetch", side_effect=fetch_stub), \
                mock.patch.object(fs.time, "sleep"), \
                mock.patch.object(sys, "argv", argv), \
                mock.patch.object(fs, "RESTATE_LOG", self.out / "statement_restatements.csv"), \
                mock.patch.object(fs, "COVERAGE_GAP_LOG", self.out / "statement_coverage_gaps.csv"), \
                mock.patch.object(fs, "COVERAGE_MIN_YEARS", min_years):
            return fs.main()

    def test_stale_code_is_refetched_and_replaced(self):
        def stub(report_name, code, timeout):
            self.calls.append((report_name, code))
            return (_api_rows(["2025-12-31", "2024-12-31", "2023-12-31"]), None)

        self.assertEqual(self._run("2026-08-24", stub), 0)
        self.assertTrue(self.calls and all(code == "000001" for _, code in self.calls))
        self.assertEqual(len(self.calls), 3)          # 三张表各命中第一套（G*）即停
        for kind in fs.STATEMENTS:
            rows = _read(self.out, kind)
            b = sorted(r["REPORT_DATE"] for r in rows if r["security_code"] == "000001")
            self.assertEqual(b, ["2023-12-31", "2024-12-31", "2025-12-31"])
            a = {r["REPORT_DATE"]: r["TOTAL_ASSETS"] for r in rows if r["security_code"] == "600519"}
            self.assertEqual(a, {"2025-12-31": "A25", "2024-12-31": "A24"})
            self.assertNotIn("TOTAL_ASSETS_YOY", rows[0])
            self.assertEqual(sum(1 for r in rows if r["security_code"] == "000001"
                                 and r["REPORT_DATE"] == "2024-12-31"), 1)   # 旧行被替换、无重复

    def test_all_current_skips_network_without_probe(self):
        def stub(report_name, code, timeout):
            self.calls.append((report_name, code))
            return ([], None)

        _write(self.out, [_row("600519", "2025-12-31"), _row("000001", "2025-12-31")])
        self.assertEqual(self._run("2026-08-24", stub), 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(_read(self.out)), 2)

    # ---- 追溯重述探针（OI-126）----
    def _settle(self):
        _write(self.out, [_row("600519", "2025-12-31", "A25", equity="100"), _row("600519", "2024-12-31", "A24"),
                          _row("000001", "2025-12-31", "B25"), _row("000001", "2024-12-31", "B24")])

    def test_probe_unchanged_leaves_rows_byte_identical(self):
        def stub(report_name, code, timeout):
            self.calls.append((report_name, code))
            return (_api_rows(["2025-12-31", "2024-12-31"], code), None)     # UPDATE_DATE 与本地同

        self._settle()
        before = {k: _read(self.out, k) for k in fs.STATEMENTS}
        self.assertEqual(self._run("2026-08-24", stub, probe=True), 0)
        self.assertEqual(sorted(self.calls), [("RPT_F10_FINANCE_GBALANCE", "000001"), ("RPT_F10_FINANCE_GBALANCE", "600519")])
        for k in fs.STATEMENTS:                                              # 只探针、不替换：retrieved_at_utc 也不动
            self.assertEqual(_read(self.out, k), before[k])
        self.assertFalse((self.out / "statement_restatements.csv").exists())

    def test_probe_refetches_restated_code_and_logs_value_change(self):
        def stub(report_name, code, timeout):
            self.calls.append((report_name, code))
            upd = {"2025-12-31": "2026-08-26"} if code == "600519" else None
            eq = "125" if code == "600519" else "100"
            return (_api_rows(["2025-12-31", "2024-12-31"], code, upd, eq), None)

        self._settle()
        self.assertEqual(self._run("2026-08-24", stub, probe=True), 0)
        by_code = {}
        for name, code in self.calls:
            by_code.setdefault(code, []).append(name)
        self.assertEqual(by_code["000001"], ["RPT_F10_FINANCE_GBALANCE"])           # 未变：只探针
        self.assertEqual(by_code["600519"], ["RPT_F10_FINANCE_GBALANCE", "RPT_F10_FINANCE_GINCOME",
                                             "RPT_F10_FINANCE_GCASHFLOW"])          # 重述：三张表整只重取
        for k in fs.STATEMENTS:
            rows = _read(self.out, k)
            a = {r["REPORT_DATE"]: (r["TOTAL_ASSETS"], r["UPDATE_DATE"]) for r in rows if r["security_code"] == "600519"}
            self.assertEqual(a["2025-12-31"], ("9", "2026-08-26"))                  # 替换成远端行
            self.assertEqual(a["2024-12-31"], ("9", "2025-04-20"))
            b = {r["REPORT_DATE"]: r["TOTAL_ASSETS"] for r in rows if r["security_code"] == "000001"}
            self.assertEqual(b, {"2025-12-31": "B25", "2024-12-31": "B24"})       # 未变的一字不动
        with (self.out / "statement_restatements.csv").open(encoding="utf-8-sig", newline="") as handle:
            log = list(csv.DictReader(handle))
        self.assertEqual([(r["security_code"], r["report_date"], r["field"], r["change_pct"]) for r in log],
                         [("600519", "2025-12-31", "TOTAL_PARENT_EQUITY", "25.00")])
        self.assertEqual((log[0]["old_update_date"], log[0]["new_update_date"]), ("2026-04-20", "2026-08-26"))

    def test_probe_failure_keeps_rows_and_is_not_a_failure(self):
        def stub(report_name, code, timeout):
            self.calls.append((report_name, code))
            return ([], "URLError")

        self._settle()
        before = {k: _read(self.out, k) for k in fs.STATEMENTS}
        self.assertEqual(self._run("2026-08-24", stub, probe=True), 0)             # 探针取不到 ≠ 失败
        self.assertEqual(len(self.calls), 8)                                        # 两只 × balance 四套口径，不再试 income/cashflow
        for k in fs.STATEMENTS:
            self.assertEqual(_read(self.out, k), before[k])

    def test_failed_refetch_keeps_old_rows(self):
        def stub(report_name, code, timeout):
            self.calls.append((report_name, code))
            return ([], "URLError")

        self.assertEqual(self._run("2026-08-24", stub), 1)
        self.assertEqual(len(self.calls), 12)         # 三张表 × 四套口径全部尝试
        rows = _read(self.out)
        b = sorted(r["REPORT_DATE"] for r in rows if r["security_code"] == "000001")
        self.assertEqual(b, ["2023-12-31", "2024-12-31"])
        self.assertEqual(len(rows), 4)

    def test_new_year_makes_every_code_stale(self):
        def stub(report_name, code, timeout):
            self.calls.append((report_name, code))
            return (_api_rows(["2026-12-31", "2025-12-31"]), None)

        self.assertEqual(self._run("2027-01-05", stub), 0)
        self.assertEqual(sorted({code for _, code in self.calls}), ["000001", "600519"])
        latest = fs.latest_period_by_code(_read(self.out))
        self.assertEqual(latest, {"000001": "2026-12-31", "600519": "2026-12-31"})

    def test_code_without_statements_is_reported_as_coverage_gap(self):
        """三表全空的代码：写覆盖缺口、告警、非零退出（不再静默让建带退回权益口径）。"""
        def stub(report_name, code, timeout):
            self.calls.append((report_name, code))
            return (([], None) if code == "300001"
                    else (_api_rows(["2026-12-31", "2025-12-31"]), None))

        self.assertEqual(self._run("2027-01-05", stub, codes=["000001", "600519", "300001"]), 1)
        with (self.out / "statement_coverage_gaps.csv").open(encoding="utf-8") as handle:
            gaps = list(csv.DictReader(handle))
        self.assertEqual([(g["security_code"], g["gap"]) for g in gaps], [("300001", "无报表")])
        self.assertEqual(gaps[0]["band_effect"], "建带静默退回权益口径")

    def test_too_few_annual_periods_is_reported_as_coverage_gap(self):
        """报表在库但年报期不足：同样入册，建带侧表现为 rejected 而非退回。"""
        def stub(report_name, code, timeout):
            self.calls.append((report_name, code))
            return (_api_rows(["2026-12-31", "2025-12-31"]), None)

        self.assertEqual(self._run("2027-01-05", stub, min_years=3), 1)
        with (self.out / "statement_coverage_gaps.csv").open(encoding="utf-8") as handle:
            gaps = list(csv.DictReader(handle))
        self.assertEqual(sorted(g["security_code"] for g in gaps), ["000001", "600519"])
        self.assertTrue(all(g["gap"] == "年报期不足" for g in gaps))


if __name__ == "__main__":
    unittest.main()
