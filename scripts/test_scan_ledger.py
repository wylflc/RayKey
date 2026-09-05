#!/usr/bin/env python3
"""台账写入口 `clean_derived_artifacts.write_ledger()` 的分流回归：现行口径行留现行台账，其余进归档，索引同步重建。"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clean_derived_artifacts as archive


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    columns = []
    for row in rows:
        columns += [c for c in row if c not in columns]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class WriteLedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.saved = (archive.MERGED, archive.ARCHIVED_LEDGER, archive.ARMS_INDEX)
        archive.MERGED = root / "backtest/scan_summaries.csv"
        archive.ARCHIVED_LEDGER = root / "archive/scan_summaries_m1.csv"
        archive.ARMS_INDEX = root / "backtest/scan_arms_index.csv"
        archive.MERGED.parent.mkdir()
        archive.ARCHIVED_LEDGER.parent.mkdir()
        self.cur = archive.METRIC_VERSION
        _write(archive.MERGED, [{"扫描标签": "BASE20091101", "策略": "BASE20091101", "计量版本": self.cur, "期末资产": "1"}])
        _write(archive.ARCHIVED_LEDGER, [{"扫描标签": "OLD20091101", "策略": "OLD20091101", "期末资产": "2", "计量版本": ""}])
        self.summaries = root / "summaries"
        self.summaries.mkdir()

    def tearDown(self) -> None:
        archive.MERGED, archive.ARCHIVED_LEDGER, archive.ARMS_INDEX = self.saved
        self.tmp.cleanup()

    def _entry(self, name: str, rows: list[dict[str, str]]) -> SimpleNamespace:
        path = self.summaries / name
        _write(path, rows)
        return SimpleNamespace(name=name, path=str(path))

    def test_rows_are_routed_by_metric_version(self) -> None:
        entries = [
            self._entry("summary_NEW20091101.csv", [{"策略": "NEW20091101", "计量版本": self.cur, "期末资产": "3"}]),
            self._entry("summary_M1A20091101.csv", [{"策略": "M1A20091101", "期末资产": "4"}]),
            self._entry("summary_M1B20091101.csv", [{"策略": "M1B20091101", "计量版本": "m1", "期末资产": "5"}]),
        ]
        upd = archive.write_ledger(entries)
        current, archived = _read(archive.MERGED), _read(archive.ARCHIVED_LEDGER)
        self.assertEqual([r["扫描标签"] for r in current], ["BASE20091101", "NEW20091101"])
        self.assertTrue(all(r["计量版本"] == self.cur for r in current))
        self.assertEqual([r["扫描标签"] for r in archived], ["OLD20091101", "M1A20091101", "M1B20091101"])
        self.assertEqual([r["期末资产"] for r in archived], ["2", "4", "5"])
        self.assertEqual((upd.current_added, upd.archive_added), (1, 2))
        arms = {r["臂名"]: r for r in _read(archive.ARMS_INDEX)}
        self.assertEqual(set(arms), {"BASE", "NEW", "OLD", "M1A", "M1B"})
        self.assertEqual(arms["M1A"]["台账"], "archive")
        self.assertEqual(arms["NEW"]["台账"], "current")
        self.assertEqual(sorted(upd.current_columns), sorted(current[0].keys()))

    def test_rerun_is_idempotent_and_same_label_is_replaced(self) -> None:
        entries = [self._entry("summary_NEW20091101.csv", [{"策略": "NEW20091101", "计量版本": self.cur, "期末资产": "3"}])]
        archive.write_ledger(entries)
        entries = [self._entry("summary_NEW20091101.csv", [{"策略": "NEW20091101", "计量版本": self.cur, "期末资产": "9"}])]
        upd = archive.write_ledger(entries)
        current = _read(archive.MERGED)
        self.assertEqual(len(current), 2)
        self.assertEqual(next(r["期末资产"] for r in current if r["扫描标签"] == "NEW20091101"), "9")
        self.assertFalse(upd.archive_changed)
        self.assertEqual(len(_read(archive.ARCHIVED_LEDGER)), 1)

    def test_stale_rows_in_current_ledger_move_to_archive(self) -> None:
        _write(archive.MERGED, [
            {"扫描标签": "BASE20091101", "策略": "BASE20091101", "计量版本": self.cur, "期末资产": "1"},
            {"扫描标签": "LEAK20091101", "策略": "LEAK20091101", "计量版本": "", "期末资产": "7"},
        ])
        upd = archive.write_ledger([], apply=False)
        self.assertFalse(archive.ARMS_INDEX.exists())
        self.assertEqual([r["扫描标签"] for r in upd.current], ["BASE20091101"])
        self.assertIn("LEAK20091101", [r["扫描标签"] for r in upd.archive])
        archive.write_ledger([])
        self.assertEqual([r["扫描标签"] for r in _read(archive.MERGED)], ["BASE20091101"])
        self.assertEqual([r["扫描标签"] for r in _read(archive.ARCHIVED_LEDGER)], ["OLD20091101", "LEAK20091101"])


if __name__ == "__main__":
    unittest.main()
