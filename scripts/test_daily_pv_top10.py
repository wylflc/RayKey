"""不筛走势的 P/V 观察表：范围、排序与交易边界的离线核验。"""
from __future__ import annotations

import contextlib
import copy
import io
import unittest
from unittest.mock import patch

import screen_daily_volume_price_signals as scan


DAY = "2026-09-15"


def quote(code, pv, **changes):
    return dict(dict(security_code=code, security_name=code, trade_date=DAY,
                     signal_state="ok", tradable=True, close=10., ma20=12., ma60=13.,
                     model_intrinsic_value=20., model_pv=pv, quality_tier="L2"), **changes)


class PVTop10Test(unittest.TestCase):
    def test_ranks_all_valued_members_without_buy_filters_or_mutation(self):
        rows = [quote(f"{n:06d}", n / 10) for n in range(1, 13)]
        rows[0].update(review_frozen=True, quality_tier="L3")
        rows[1].update(model_pv="0.1", hold_pv="0.001")
        rows[0]["hold_pv"] = "9.0"
        rows[2].update(close=14., ma20=13., ma60=12.)
        rows[3].update(model_pv=1.5)  # 超买入线仍可入观察表（若排名够低）。
        rows.reverse()
        before = copy.deepcopy(rows)
        ranked = scan.build_pv_top10(rows, DAY, set(), {r["security_code"] for r in rows})
        self.assertEqual([r["security_code"] for r in ranked],
                         ["000001", "000002", "000003", "000005", "000006",
                          "000007", "000008", "000009", "000010", "000011"])
        self.assertEqual(ranked[0]["trend_status"], "未达标（新建仓）")
        self.assertEqual(ranked[2]["trend_status"], "达标（新建仓）")
        self.assertGreater(ranked[-1]["model_pv"], scan.SEC93_BUY_LINE)
        self.assertEqual(rows, before)

    def test_invalid_pv_quotes_dates_and_outside_members_are_excluded(self):
        rows = [quote(f"{n:06d}", pv) for n, pv in enumerate(("", "bad", "nan", "inf", 0, -1), 1)]
        rows += [quote("000007", .1, trade_date="2026-09-14"),
                 quote("000008", .1, tradable="False"),
                 quote("000009", .1, signal_state="data_error"),
                 quote("000010", .1, close=float("nan")),
                 quote("000011", .1, close=0), quote("000012", .1),
                 quote("000013", .2)]
        members = {r["security_code"] for r in rows} - {"000012"}
        self.assertEqual([r["security_code"] for r in scan.build_pv_top10(rows, DAY, set(), members)],
                         ["000013"])

    def test_missing_averages_keep_rank_and_held_trend_uses_addon_rule(self):
        rows = [quote("000001", .1, ma20="", ma60="", signal_state="insufficient_price_history"),
                quote("000002", .2, ma20=12., ma60=11.),
                quote("000003", .3, ma20=12., ma60=11.),
                quote("000004", .4, close=12., ma20=12., ma60=11.)]
        ranked = scan.build_pv_top10(rows, DAY, {"000002"}, {r["security_code"] for r in rows})
        self.assertEqual([r["trend_status"] for r in ranked],
                         ["数据不足（新建仓）", "达标（加仓）", "未达标（新建仓）", "未达标（新建仓）"])

    def test_short_history_still_has_current_quote_date(self):
        history = [dict(date=DAY, close=10., raw_close=10., volume=100., amount=1000.)]
        with patch.object(scan, "fetch_daily_rows", return_value=("test", history)):
            row = scan.scan_one(dict(security_code="000001"), DAY, 1.)
        self.assertEqual(row["trade_date"], DAY)
        self.assertEqual(row["close"], 10.)
        self.assertEqual(row["signal_state"], "insufficient_price_history")

    def test_empty_and_partial_tables_are_explicit(self):
        for rows, expected in (([], "观察名单为空"), ([quote("000001", .3)], "仅 1 只")):
            ranked = scan.build_pv_top10(rows, DAY, set(), {r["security_code"] for r in rows})
            with contextlib.redirect_stdout(io.StringIO()) as out:
                scan.report_pv_top10(ranked, DAY)
            self.assertIn(expected, out.getvalue())
            self.assertIn(DAY, out.getvalue())


if __name__ == "__main__":
    unittest.main()
