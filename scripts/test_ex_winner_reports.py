"""第4款的比率阈值与缺路径不得在剂量/对称性报表中静默通过。"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experimental import ex_winner_symmetry_report as report
from sweep_backtest_configs import FIELDS, metric_header


class ReportTests(unittest.TestCase):
    def run_report(self, missing=False, series=True):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'dose.txt'
            rows = [metric_header(), '#SET|K1@CHECK|000001']
            for label in ('BASE', 'ARM'):
                for start in ('2010-05-01', '2010-11-01'):
                    if missing and label == 'ARM' and start == '2010-11-01':
                        continue
                    vals = dict.fromkeys(FIELDS, 0.5)
                    if label == 'ARM':
                        vals['Sharpe'] -= 0.01  # 比率差应以0.005判断，不能用0.15。
                    rows.append(f'EX5:K1@CHECK{label}|{start}|'+'|'.join(str(vals[k]) for k in FIELDS))
                    if series:   # m3：同窗序列行（主读数原料）；缺它的文件不能按 m3 判
                        rows.append(f'#WIN5|EX5:K1@CHECK{label}|{start}|2015-05=0.5;2015-06=0.6;2015-07=0.4')
            path.write_text('\n'.join(rows)+'\n')
            out = io.StringIO()
            with patch.object(sys, 'argv', ['report', str(path), '--challenger', 'ARM']), contextlib.redirect_stdout(out):
                report.main()
            return out.getvalue()

    def test_ratio_threshold(self):
        self.assertIn('Sharpe -0.010', self.run_report())

    def test_missing_paired_path_rejected(self):
        with self.assertRaisesRegex(ValueError, '起点不齐'):
            self.run_report(missing=True)

    def test_missing_window_series_rejected(self):
        with self.assertRaisesRegex(ValueError, '缺同窗序列'):
            self.run_report(series=False)
        self.assertIn('Δ主(滚5同窗)', self.run_report())


if __name__ == '__main__':
    unittest.main()
