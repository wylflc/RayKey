"""§12.1 买入线对齐容差（v4.169，OI-168）：容差内保留原线，超出才重解到同一在册合格面。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "experimental"))
from align_buy_line import resolve_line  # noqa: E402


def arm_with_share(share: float, line: float, n: int = 10000) -> list[float]:
    """构造升序观测：恰有 share 比例 ≤ line。"""
    k = int(round(share * n))
    return sorted([line - 0.5 + 0.5 * i / k for i in range(k)] + [line + 0.001 + i / (n - k) for i in range(n - k)])


class AlignToleranceTests(unittest.TestCase):
    def test_within_tolerance_keeps_line_and_registered_share(self):
        arm = arm_with_share(0.1793, 1.0454)                     # OI-168：原线合格面 17.93% 对在册 17.77%
        line, got, old, kept = resolve_line(arm, 1.0454, 0.1777, 0.2)
        self.assertTrue(kept)
        self.assertEqual(line, 1.0454)
        self.assertAlmostEqual(old, 0.1793, places=4)
        self.assertEqual(got, old)

    def test_beyond_tolerance_realigns_to_registered_share(self):
        arm = arm_with_share(0.1850, 1.0454)                     # 差 0.73pp ≥ 0.2pp → 重解
        line, got, old, kept = resolve_line(arm, 1.0454, 0.1777, 0.2)
        self.assertFalse(kept)
        self.assertLess(line, 1.0454)
        self.assertAlmostEqual(got, 0.1777, delta=0.0002)
        self.assertEqual(line, round(line, 4))

    def test_boundary_is_strict(self):
        arm = arm_with_share(0.1797, 1.0454)                     # 恰差 0.2pp → 不在容差内
        self.assertFalse(resolve_line(arm, 1.0454, 0.1777, 0.2)[3])
        self.assertTrue(resolve_line(arm, 1.0454, 0.1777, 0.21)[3])

    def test_zero_tolerance_reproduces_old_behaviour(self):
        arm = arm_with_share(0.1793, 1.0454)
        line, got, old, kept = resolve_line(arm, 1.0454, 0.1777, 0.0)
        self.assertFalse(kept)
        self.assertAlmostEqual(got, 0.1777, delta=0.0002)


if __name__ == "__main__":
    unittest.main()
