"""Regression checks for classification display and the model-only dossier path."""
from __future__ import annotations

import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apply_forecast_band_overlay as overlay
import apply_model_bands_to_dossiers as dossiers
import build_a_share_core_valuation_pool as pool
import build_company_dossier_readmes as readmes
import build_overseas_roic_bands as overseas


def write_csv(path, rows, fields=None):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ClassificationDisplayTests(unittest.TestCase):
    def test_boundary_status_wins_over_stale_tier(self):
        row = dict(security_code='000001', security_name='待核验公司', notes='用户点名建档',
                   band_low='90', band_high='110', band_method='ROIC', band_derivation='model',
                   reviewed_at='2026-09-08')
        tiers = {'000001': {'quality_tier': 'L4', 'quality_score': '60'}}
        triage = [{'security_code': '000001', 'attention_class': 'boundary_pending'}]
        lines, _ = pool.build_off_pool_dossier_section([row], triage, tiers=tiers)
        self.assertIn('| — | boundary_pending |', '\n'.join(lines))
        self.assertNotIn('| L4 |', '\n'.join(lines))
        with patch.dict(readmes.TRIAGE_CLASS, {'000001': 'boundary_pending'}, clear=True):
            text, _ = readmes.render(row, {}, {}, tiers)
        self.assertIn('boundary_pending（不评分）', text)
        self.assertNotIn('参考分 60', text)

    def test_overseas_history_is_retained_once_and_not_a_current_rating(self):
        row = dict(security_code='TEST', security_name='测试公司', attention_class='boundary_pending',
                   quality_tier='L4', quality_score='60', fair_price_low='90', fair_price_high='110')
        prior = '# 测试公司\n\n旧研究与估值 500\n\n## ROIC 口径估值\n\n被更新的模型 200'
        text = overseas.render_readme(row, prior)
        self.assertEqual(text, overseas.render_readme(row, text))
        current, history = text.split('<details>', 1)
        self.assertNotIn('500', current)
        self.assertNotIn('| L4 |', current)
        self.assertNotIn('| 60 |', current)
        self.assertIn('旧研究与估值 500', history)

    def test_pending_label_preserves_overseas_model_parameters_and_results(self):
        years, inputs = overseas.load_years(), overseas.load_inputs()
        # Compare full calculations using the locally registered annual and TTM inputs.
        for code in ('09992', '06862', '00316'):
            with self.subTest(code=code):
                old = overseas.value_company(code, 'L4', years[code], inputs, overseas.load_years.current.get(code))
                new = overseas.value_company(code, 'boundary_pending', years[code], inputs,
                                              overseas.load_years.current.get(code))
                self.assertEqual(old['status'], 'ok')
                self.assertEqual(old, new)


class DossierModelPathTests(unittest.TestCase):
    def test_manual_input_rejected_before_output_even_if_already_normalized(self):
        row = dict(security_code='000001', status='ok', intrinsic_value='100',
                   available_at='2026-09-01', report_date='2026-06-30',
                   forecast_overlay='manual_override', exright_note='already normalized')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bands.csv'; write_csv(path, [row])
            before = path.read_bytes()
            with patch('sys.argv', ['overlay', '--signal-date', '2026-09-07', '--bands', str(path)]), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(overlay.main(), 1)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                dossiers.latest_model_bands(path, '2025-01-01')
            with self.assertRaises(ValueError):
                overlay.exright_normalize(row, [], '2026-09-07')

    def test_retired_override_cli_is_rejected(self):
        with patch('sys.argv', ['overlay', '--signal-date', '2026-09-07', '--overrides', 'old.csv']), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            overlay.main()
        self.assertEqual(exc.exception.code, 2)

    def test_interest_rate_uses_signal_cutoff_not_file_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / 'data/reference'; target.mkdir(parents=True)
            write_csv(target / 'cost_of_equity_inputs.csv', [
                {'observed_on': '2026-09-08', 'risk_free_rate': '0.01'},
                {'observed_on': '2026-09-04', 'risk_free_rate': '0.02'},
                {'observed_on': '2026-08-31', 'risk_free_rate': '0.03'}])
            with patch.object(dossiers, 'ROOT', root):
                self.assertEqual(dossiers.latest_rf('2026-09-07'), 0.02)
                self.assertIsNone(dossiers.latest_rf('2026-08-01'))

    def test_dossier_writer_uses_model_and_signal_day_corporate_actions(self):
        band = dict(security_code='000001', status='ok', intrinsic_value='100', band_low='90',
                    band_high='110', available_at='2026-09-01', notice_date='2026-09-01',
                    report_date='2026-06-30', roic_path='equity_fallback')
        row = dict(security_code='000001', security_name='测试公司', band_low='90', band_high='110',
                   notes='研究证据', bespoke='true', band_derivation='', band_method='', decided_by='',
                   anchor_earnings_yi='', reviewed_at='')
        action = dict(ex_dividend_date='2026-09-08', cash_per_share='2', share_ratio='1')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); bands = root / 'bands.csv'; target = root / 'dossiers.csv'
            legacy = root / 'data/processed'; legacy.mkdir(parents=True)
            write_csv(legacy / 'manual_band_overrides.csv', [{'security_code': '000001', 'band_low': '900', 'band_high': '1100'}])
            future = {**band, 'available_at': '2026-09-20', 'intrinsic_value': '500'}
            write_csv(bands, [band, future])
            for day, low, high in [('2026-09-07', '90.00', '110.00'), ('2026-09-08', '44.10', '53.90')]:
                with self.subTest(day=day):
                    write_csv(target, [row])
                    argv = ['dossiers', '--signal-date', day, '--bands', str(bands), '--dossiers', str(target),
                            '--archive-bands', str(root / 'missing.csv')]
                    with patch('sys.argv', argv), patch.object(dossiers, 'ROOT', root), \
                            patch.object(dossiers, 'load_actions', return_value={'000001': [action]}), \
                            contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(dossiers.main(), 0)
                    with target.open() as handle:
                        result = next(csv.DictReader(handle))
                    self.assertEqual((result['band_low'], result['band_high']), (low, high))
                    self.assertIn('研究证据', result['notes'])


if __name__ == '__main__':
    unittest.main()
