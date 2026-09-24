"""OI-205：峰谷守卫只对策略标签 H／F 生效；补判表只收标签表之外的代码。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cycle_guard_scope as scope  # noqa: E402


def _write(path: Path, header: str, rows: list[str]) -> Path:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


class CycleGuardScopeTest(unittest.TestCase):
    def test_only_h_and_f_tags_keep_the_guard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tags = _write(Path(td) / "tags.csv", "security_code,strategy_tag_letter", ["000858,A", "600160,H", "601899,F"])
            sup = _write(Path(td) / "sup.csv", "security_code,guard_class", ["600585,H", "600009,K"])
            self.assertEqual(scope.cyclical_codes(tags, sup), {"600160", "601899", "600585"})

    def test_supplement_may_not_override_a_strategy_tag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tags = _write(Path(td) / "tags.csv", "security_code,strategy_tag_letter", ["000858,A"])
            sup = _write(Path(td) / "sup.csv", "security_code,guard_class", ["000858,H"])
            with self.assertRaises(ValueError):
                scope.cyclical_codes(tags, sup)

    def test_repository_files_load(self) -> None:
        codes = scope.cyclical_codes()
        self.assertIn("600160", codes)          # 巨化股份 H
        self.assertNotIn("000858", codes)       # 五粮液 A
        self.assertIn("600585", codes)          # 海螺水泥（补判 H）


if __name__ == "__main__":
    unittest.main()
