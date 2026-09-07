#!/usr/bin/env python3
"""结案清理边界，以及清理后实验重建入口的回归。"""
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "experimental"))
import clean_derived_artifacts as cleanup
import make_shortlist_configs as shortlist


class ClosedCleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        self.write(".gitignore", "data/experiments/\n")
        self.write("docs/Ashare_workflow_open_issues_closed.md", "| OI-141 | 已结案 |\n")
        self.write("docs/Ashare_workflow_open_issues.md", "## 待处理\n")
        self.addCleanup(patch.stopall)
        patch.object(cleanup, "ROOT", self.root).start()
        patch.object(cleanup, "CLOSED_EXPERIMENTS", {"exp_oi141": (141,)}).start()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def write(self, relative, text="test\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def collected(self):
        return {p for paths in cleanup.collect_closed_experiments().values() for p in paths}

    def test_apply_only_removes_reviewed_ignored_derivatives(self):
        prefix = "data/experiments/exp_oi141"
        removable = [self.write(f"{prefix}/val/DIVS01/states_base.csv"),
                     self.write(f"{prefix}/val/DIVS01/roic_bands.csv"),
                     self.write(f"{prefix}/sig/DIVS01/candidates.csv")]
        tracked = self.write(f"{prefix}/val/DIVS01/states_hold.csv")
        self.git("add", "-f", str(tracked.relative_to(self.root)))
        kept = [tracked, self.write(f"{prefix}/val/DIVS01/align_buy_line.txt"),
                self.write(f"{prefix}/report.md"), self.write(f"{prefix}/configs/arms.tsv"),
                self.write(f"{prefix}/summaries/summary_BASE.csv"),
                self.write(f"{prefix}/raw/states_base.csv"),
                self.write("data/experiments/exp_oi150_overseas_forward/val/A/states_base.csv"),
                self.write("data/processed/a_share_daily_states_adopted.csv")]
        self.assertEqual(self.collected(), set(removable))
        with contextlib.redirect_stdout(io.StringIO()):
            cleanup.clean_closed_experiments(apply=False)
        self.assertTrue(all(p.exists() for p in removable + kept))
        with contextlib.redirect_stdout(io.StringIO()):
            cleanup.clean_closed_experiments(apply=True)
        self.assertTrue(all(not p.exists() for p in removable))
        self.assertTrue(all(p.read_text() == "test\n" for p in kept))
        self.assertEqual(self.collected(), set())

    def test_reopened_or_referenced_experiment_is_preserved(self):
        self.write("data/experiments/exp_oi141/val/A/states_base.csv")
        for opened in ("### OI-141｜重开\n", "复用 exp_oi141 的状态文件\n"):
            with self.subTest(opened=opened):
                self.write("docs/Ashare_workflow_open_issues.md", opened)
                self.assertEqual(self.collected(), set())
        self.write("docs/Ashare_workflow_open_issues.md", "")
        self.write("docs/Ashare_workflow_open_issues_closed.md", "")
        self.assertEqual(self.collected(), set())

    def test_symlinked_files_and_directories_are_preserved(self):
        target = self.write("data/processed/production.csv")
        directory = self.root / "data/experiments/exp_oi141/val/A"
        directory.mkdir(parents=True)
        (directory / "states_base.csv").symlink_to(target)
        (directory.parent / "B").symlink_to(target.parent, target_is_directory=True)
        self.assertEqual(self.collected(), set())
        self.assertEqual(target.read_text(), "test\n")


class ShortlistRebuildTest(unittest.TestCase):
    def test_cached_alignment_does_not_hide_deleted_or_empty_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = Path(tmp)
            directory = exp / "val/DIVS03"
            directory.mkdir(parents=True)
            (directory / "align_buy_line.txt").write_text("--width -0.1311\n")
            row = {"label": "DIVS03", "build_extra": "-", "divspread": "0.03"}
            self.assertFalse(shortlist.build_ready(exp, row))
            for side in ("base", "b2", "hold"):
                (directory / f"states_{side}.csv").write_text("code,date\n")
            self.assertTrue(shortlist.build_ready(exp, row))
            (directory / "states_hold.csv").write_text("")
            self.assertFalse(shortlist.build_ready(exp, row))
            (directory / "states_hold.csv").unlink()
            self.assertFalse(shortlist.build_ready(exp, row))

    def test_universe_only_arm_does_not_require_valuation_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = Path(tmp)
            directory = exp / "val/U6A"
            directory.mkdir(parents=True)
            (directory / "align_buy_line.txt").write_text("--width -0.1953\n")
            row = {"label": "U6A", "build_extra": "-", "divspread": "-"}
            self.assertTrue(shortlist.build_ready(exp, row))


if __name__ == "__main__":
    unittest.main()
