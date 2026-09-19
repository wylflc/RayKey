"""换码参考表的两条派生规则（OI-192）：事件复制到旧码、面板区间不跨越换码日。"""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import code_succession as cs

PAIR = {"old_code": "000022", "old_name": "深赤湾A", "new_code": "001872", "new_name": "招商港口",
        "last_old_trading_date": "2018-12-20", "first_new_trading_date": "2018-12-26", "source": "", "note": ""}


def action(code, ex, cash="0.1", ratio="0", rights="", plan_notice=""):
    return {"security_code": code, "security_name": "招商港口" if code == "001872" else "x",
            "ex_dividend_date": ex, "cash_per_share": cash, "share_ratio": ratio, "plan": "",
            "report_date": "", "plan_notice_date": plan_notice, "progress": "", "rights_ratio": rights,
            "rights_price": ""}


class ExpandActionsTest(unittest.TestCase):
    def test_copies_only_events_on_or_before_last_old_day(self):
        rows = [action("001872", "2018-05-23"), action("001872", "2018-12-20"), action("001872", "2019-07-10"),
                action("001872", "", plan_notice="2026-08-01"), action("600036", "2018-07-12")]
        out, added = cs.expand_actions(rows, [PAIR])
        self.assertEqual(added, 2)
        clones = [r for r in out if r["security_code"] == "000022"]
        self.assertEqual([r["ex_dividend_date"] for r in clones], ["2018-05-23", "2018-12-20"])
        self.assertTrue(all(r["security_name"] == "深赤湾A" for r in clones))
        self.assertEqual(len([r for r in out if r["security_code"] == "001872"]), 4)  # 新码行原样保留

    def test_existing_old_code_rows_are_not_overwritten_and_rights_key_is_separate(self):
        kept = action("000022", "2018-05-23", cash="9.9")
        rows = [kept, action("001872", "2018-05-23"), action("001872", "2018-05-23", cash="0", rights="0.3")]
        out, added = cs.expand_actions(rows, [PAIR])
        self.assertEqual(added, 1)
        old_rows = [r for r in out if r["security_code"] == "000022"]
        self.assertEqual({r["cash_per_share"] for r in old_rows}, {"9.9", "0"})
        out2, added2 = cs.expand_actions(out, [PAIR])
        self.assertEqual((len(out2), added2), (len(out), 0))  # 幂等

    def test_no_pairs_returns_rows_unchanged(self):
        rows = [action("001872", "2018-05-23")]
        self.assertEqual(cs.expand_actions(rows, []), (rows, 0))


class CheckPanelTest(unittest.TestCase):
    def test_conflicts_are_reported_per_row(self):
        rows = [{"security_code": "000022", "effective_from": "2005-04-30", "effective_to": "2016-04-30"},
                {"security_code": "001872", "effective_from": "2009-04-30", "effective_to": "2010-04-30"},
                {"security_code": "000022", "effective_from": "2017-04-30", "effective_to": ""},
                {"security_code": "600036", "effective_from": "2009-04-30", "effective_to": ""}]
        defects = cs.check_panel(rows, [PAIR])
        self.assertEqual(len(defects), 2)
        self.assertIn("001872", defects[0])
        self.assertIn("000022", defects[1])

    def test_clean_panel_passes(self):
        rows = [{"security_code": "000022", "effective_from": "2005-04-30", "effective_to": "2016-04-30"},
                {"security_code": "001872", "effective_from": "2018-12-26", "effective_to": ""}]
        self.assertEqual(cs.check_panel(rows, [PAIR]), [])


class LoadAndApplyTest(unittest.TestCase):
    def test_load_validates_dates_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.csv"
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cs.FIELDS)
                w.writeheader()
                w.writerow({**PAIR, "last_old_trading_date": "2018-12-26", "first_new_trading_date": "2018-12-20"})
            with self.assertRaises(ValueError):
                cs.load_succession(path)
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cs.FIELDS)
                w.writeheader()
                w.writerow(PAIR)
                w.writerow(PAIR)
            with self.assertRaises(ValueError):
                cs.load_succession(path)
            self.assertEqual(cs.load_succession(Path(tmp) / "missing.csv"), [])

    def test_apply_actions_file_rewrites_sorted_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "actions.csv"
            fields = list(action("001872", "2018-05-23"))
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows([action("600036", "2018-07-12"), action("001872", "2018-05-23"), action("001872", "2019-07-10")])
            with patch.object(cs, "load_succession", return_value=[PAIR]):
                self.assertEqual(cs.apply_actions_file(path), 1)
                self.assertEqual(cs.apply_actions_file(path), 0)
            with path.open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([(r["security_code"], r["ex_dividend_date"]) for r in rows],
                             [("000022", "2018-05-23"), ("001872", "2018-05-23"), ("001872", "2019-07-10"), ("600036", "2018-07-12")])


if __name__ == "__main__":
    unittest.main()
