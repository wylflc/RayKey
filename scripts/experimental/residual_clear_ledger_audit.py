#!/usr/bin/env python3
"""从净额成交与公司行动重建卖出日余仓；与引擎每日持仓数交叉核验。"""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from backtest_valuation_strategy import load_actions


def audit(folder, actions):
    curve = list(csv.DictReader(next(folder.glob('*_equity.csv')).open()))
    orders = list(csv.DictReader((folder / 'ledger.csv').open()))
    by_day = defaultdict(list)
    for row in orders:
        by_day[row['date']].append(row)
    held = defaultdict(float)
    counts = defaultdict(int)
    events, mismatches = [], []
    for point in curve:
        day = point['date']
        for code in list(held):
            action = actions.get(code, {}).get(day)
            if action:
                held[code] *= 1 + action[1] + action[2]
        sold = {}
        for row in by_day[day]:
            code, shares = row['security_code'], float(row['shares'])
            if row['action'] == '买入':
                held[code] += shares
                counts['buy_orders'] += 1
            elif row['action'] == '卖出':
                held[code] -= shares
                sold[code] = row
                counts['sell_orders'] += 1
                # 流水股数只保留整数，清仓后允许小于一股的数值残差。
                if abs(held[code]) < 1:
                    held.pop(code)
            else:
                raise ValueError(row['action'])
        if any(v < -1 for v in held.values()):
            raise ValueError(f'{folder.name} {day}: negative reconstructed holdings')
        actual_count = sum(v >= 1 for v in held.values())
        if actual_count != int(point['positions']):
            mismatches.append([day, actual_count, int(point['positions'])])
        for code, row in sold.items():
            left = held.get(code, 0)
            counts['sell_code_days'] += 1
            if left < 1:
                counts['sell_code_days_closed'] += 1
                continue
            # 便利性描述统一按当日日末净资产与最后卖价计，不充当引擎触发判据。
            ratio = left * float(row['price']) / (float(point['net_equity']) * .05)
            event = {'date': day, 'code': code, 'name': row['security_name'],
                     'remaining_shares': round(left, 4), 'remaining_tranches': ratio,
                     'sell_price': float(row['price']),
                     'reason': row['reason']}
            if abs(left - 100) < 1:
                counts['remaining_100_shares'] += 1
            for threshold in [.1, .5, 1.5]:
                if ratio < threshold:
                    counts[f'remaining_below_{threshold}_tranches'] += 1
            events.append(event)
    assert not mismatches, f'{folder.name}: holding count mismatches {mismatches[:10]}'
    return {'counts': dict(counts), 'days_checked': len(curve), 'holding_count_mismatches': 0,
            'end_date': curve[-1]['date'], 'events': events}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--labels', default='BASE,RC150')
    args = ap.parse_args()
    exp = ROOT / 'data/experiments/exp_residual_clear'
    actions = load_actions()
    result = {label: audit(exp / 'sig' / label, actions) for label in args.labels.split(',')}
    (exp / 'ledger_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    for label, record in result.items():
        print(label, record['counts'], 'holding-count check:', record['days_checked'])


if __name__ == '__main__':
    main()
