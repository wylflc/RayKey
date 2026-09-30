"""§7.3 结构性增长复核（OI-249）判定逻辑：量驱动（放宽后 w = 0）且峰守卫砍掉每股 NOPAT ≥ 40% 才标记。"""
import unittest

import structural_growth_review as sgr


def _band(w: float, nopat: float, value: float = 10.0) -> dict[str, str]:
    return {"status": "ok", "peak_weight": f"{w:.3f}", "nopat_ps": f"{nopat:.4f}", "intrinsic_value": f"{value:.4f}"}


class ReviewTest(unittest.TestCase):
    key = ("300308", "2025-03-31", "2025-04-21")
    pool = [{"security_code": "300308", "security_name": "中际旭创", "report_date": "2025-03-31", "available_at": "2025-04-21"}]

    def run_review(self, guarded, relaxed):
        return sgr.review(self.pool, {self.key: guarded}, {self.key: relaxed}, "2025-04-18",
                          industry={"300308": ("电子设备-光电子器件-光通信", False)})[0]

    def test_volume_driven_cut_above_threshold_is_flagged(self) -> None:
        row = self.run_review(_band(1.0, 2.9042), _band(0.0, 6.2277))
        self.assertTrue(row["volume_driven"])
        self.assertTrue(row["flagged"])
        self.assertAlmostEqual(float(row["cut"]), 1 - 2.9042 / 6.2277, places=4)

    def test_small_cut_is_volume_driven_but_not_flagged(self) -> None:
        row = self.run_review(_band(0.3, 3.6), _band(0.0, 4.0))
        self.assertTrue(row["volume_driven"])
        self.assertFalse(row["flagged"])

    def test_guard_kept_when_not_volume_driven(self) -> None:
        row = self.run_review(_band(1.0, 2.0), _band(1.0, 2.0))
        self.assertFalse(row["volume_driven"])
        self.assertFalse(row["flagged"])
        self.assertEqual(row["cut"], "")

    def test_missing_rebuilt_band_is_reported(self) -> None:
        row = sgr.review(self.pool, {}, {}, "2025-04-18")[0]
        self.assertEqual(row["band_match"], "missing")
        self.assertFalse(row["flagged"])


if __name__ == "__main__":
    unittest.main()
