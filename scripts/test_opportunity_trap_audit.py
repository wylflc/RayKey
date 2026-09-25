"""§12.1 第 13 款机会／陷阱读数（OI-222）：答案卷分类边界、合段规则、估值层与策略层读数、具名案例与成文阈值同步。"""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import opportunity_trap_audit as audit  # noqa: E402
import opportunity_trap_labels as lab  # noqa: E402


def row(code, month, label, day='28'):
    return dict(code=code, month=month, date=f'{month}-{day}', label=label, panel=True)


class LabelTest(unittest.TestCase):
    def test_boundaries(self):
        L = lab.label
        self.assertEqual(L(0.20, 0.0, 0.10), '机会')                  # 三个门槛恰好取等
        self.assertEqual(L(0.20, -0.30, 0.10, growth5=0.05), '机会')  # 3 年盈利低谷、5 年恢复
        self.assertEqual(L(0.20, -0.30, 0.10, growth5=-0.01), '估值扩张')
        self.assertEqual(L(0.35, 0.50, 0.09), '一般')                 # 超额不足 10pp：随大盘上涨不算机会
        self.assertEqual(L(0.0, -0.20, -0.10), '陷阱')
        self.assertEqual(L(0.0, -0.19, -0.10), '一般')                # 盈利只降 19%
        self.assertEqual(L(-0.20, -0.50, -0.05), '一般')              # 跟随大盘下跌不算陷阱
        self.assertEqual(L(0.01, -0.50, -0.20), '一般')               # 3 年仍赚钱
        self.assertIsNone(L(0.30, None, 0.2))
        self.assertIsNone(L(0.30, 0.1, None))

    def test_episode_gap(self):
        rows = [row('A', '2010-01', '机会'), row('A', '2010-02', '机会'), row('A', '2010-04', '机会'),   # 中断 1 个月：同一段
                row('A', '2010-07', '机会'),                                                           # 中断 2 个月：新段
                row('A', '2010-08', '陷阱'), row('B', '2010-01', '一般'), row('B', '2010-02', '陷阱')]
        eps = lab.episodes(rows)
        self.assertEqual([(e[0]['code'], e[0]['label'], e[0]['month'], len(e)) for e in eps],
                         [('A', '机会', '2010-01', 3), ('A', '机会', '2010-07', 1), ('A', '陷阱', '2010-08', 1), ('B', '陷阱', '2010-02', 1)])


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.rows = [row('A', '2010-01', '机会'), row('A', '2010-02', '机会'), row('A', '2010-03', '一般'),
                     row('B', '2010-01', '陷阱'), row('B', '2010-02', '陷阱'), row('B', '2010-03', '一般'),
                     row('C', '2010-01', '一般'), row('C', '2010-02', '机会')]
        self.eps = lab.episodes(self.rows)
        for i, ep in enumerate(self.eps):
            for r in ep:
                r['episode'] = i
        # A 的第二个机会月进买入区、B 的第一个陷阱月进买入区、C 无法估值、A 第三月无状态行
        self.pv = {('A', '2010-01-28'): 1.5, ('A', '2010-02-28'): 0.9, ('B', '2010-01-28'): 1.0, ('B', '2010-02-28'): 1.3,
                   ('B', '2010-03-28'): 0.8, ('C', '2010-01-28'): None, ('C', '2010-02-28'): None}

    def test_rates(self):
        stocks, c = audit.counts(self.rows, self.pv, 1.067, len(self.eps))
        r = audit.rates(c)
        self.assertEqual(stocks, ['A', 'B', 'C'])
        self.assertAlmostEqual(r['zone_share'], 3 / 8)
        self.assertAlmostEqual(r['opp_capture_m'], 1 / 3)      # A-02 进区；A-01 未进；C-02 无法估值
        self.assertAlmostEqual(r['opp_capture_e'], 1 / 2)      # A 段命中，C 段未命中
        self.assertAlmostEqual(r['zone_opp_share'], 1 / 3)
        self.assertAlmostEqual(r['zone_trap_share'], 1 / 3)
        self.assertAlmostEqual(r['trap_hit_m'], 1 / 2)
        self.assertAlmostEqual(r['trap_hit_e'], 1.0)
        self.assertAlmostEqual(r['opp_nopv'], 1 / 3)           # 只有 C-02 无法估值；A-01 有 P/V、只是不在区内
        self.assertAlmostEqual(r['base_opp'], 3 / 8)
        self.assertAlmostEqual(r['lift_trap'], (1 / 3) / (2 / 8))

    def test_bootstrap_uses_stock_clusters(self):
        _s, c = audit.counts(self.rows, self.pv, 1.067, len(self.eps))
        draws = audit.bootstrap({'X': c}, 3)
        self.assertEqual(len(draws[('X', 'zone_share')]), audit.BOOT)
        w = np.array([2.0, 0.0, 1.0])                           # 抽到 A 两次、C 一次
        self.assertAlmostEqual(audit.rates(c, w)['opp_capture_m'], 2 / 5)

    def test_case_and_strategy_readings(self):
        cases = [dict(case_id='O1', kind='机会', security_code='A', window_start='2010-01', window_end='2010-02'),
                 dict(case_id='T1', kind='陷阱', security_code='B', window_start='2010-01', window_end='2010-02')]
        out = audit.case_readings(cases, self.rows, self.pv, 1.067)
        self.assertEqual((out[0]['zone_months'], out[0]['months'], out[0]['first_zone'], out[0]['min_pv']), (1, 2, '2010-02', 0.9))
        self.assertEqual((out[1]['zone_months'], out[1]['first_zone']), (1, '2010-01'))
        trades = {'s1': [dict(code='A', entry='2010-02-03', exit='2010-05-01', invested=100.0, contrib=0.05),
                         dict(code='B', entry='2010-01-05', exit='2010-01-20', invested=300.0, contrib=-0.02),
                         dict(code='A', entry='2024-01-05', exit='2024-02-01', invested=100.0, contrib=0.01)],
                  's2': [dict(code='C', entry='2010-03-10', exit='2010-04-01', invested=50.0, contrib=0.0)]}
        s = audit.strategy_readings(trades, self.rows, cases, '2023-08')
        self.assertEqual(s['starts'], 2)
        self.assertEqual(s['cases']['O1']['held_starts'], 1)
        self.assertAlmostEqual(s['cases']['O1']['contrib_median'], 0.025)   # 两个起点：0.05 与 0
        self.assertAlmostEqual(s['by_label']['未满3年']['contrib'], 0.005)
        self.assertAlmostEqual(s['by_label']['无标签']['cycles'], 0.5)       # C-03 不在答案卷（本例无该行）


class SyncTest(unittest.TestCase):
    def test_workflow_thresholds(self):
        text = (ROOT / 'docs/000_Ashare_workflow.md').read_text(encoding='utf-8')
        t = lab.THRESHOLDS
        self.assertEqual(t, dict(opp_return=0.20, opp_excess=0.10, opp_growth=0.0, trap_return=0.0, trap_excess=-0.10, trap_growth=-0.20))
        self.assertIn('**机会** = `f3` ≥ 20%、超额 ≥ +10pp，且 3 年或 5 年后盈利不低于当时', text)
        self.assertIn('**陷阱** = `f3` ≤ 0、超额 ≤ −10pp，且 3 年后盈利降 ≥ 20%', text)
        self.assertIn('（中断不超过 1 个月）的同类标签合为一段', text)
        self.assertEqual(lab.EPISODE_GAP, 2)
        for path in ('data/backtest/opportunity_trap_labels_v1.csv', 'data/reference/opportunity_trap_cases.csv',
                     'scripts/experimental/opportunity_trap_labels.py', 'scripts/experimental/opportunity_trap_audit.py'):
            self.assertIn(f'`{path}`', text)
            self.assertTrue((ROOT / path).exists(), path)

    def test_registered_cases_sit_inside_episodes(self):
        rows, eps = audit.load_answer_key(audit.LABELS)
        cases = audit.load_cases(audit.CASES, eps)
        self.assertEqual(sorted({c['kind'] for c in cases}), ['机会', '陷阱'])
        self.assertEqual(len({c['case_id'] for c in cases}), len(cases))


if __name__ == '__main__':
    unittest.main()
