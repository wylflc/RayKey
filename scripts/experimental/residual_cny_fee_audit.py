#!/usr/bin/env python3
"""固定金额清尾的实际净额流水、最低佣金溢价与余仓复核。"""
import argparse
from collections import defaultdict
import csv
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from backtest_valuation_strategy import load_actions
from experimental.residual_clear_ledger_audit import audit


def fee_audit(folder):
    curve = list(csv.DictReader(next(folder.glob('*_equity.csv')).open()))
    equity = {r['date']: float(r['net_equity']) for r in curve}
    previous = {b['date']: float(a['net_equity']) for a,b in zip(curve,curve[1:])}
    years = (date.fromisoformat(curve[-1]['date'])-date.fromisoformat(curve[0]['date'])).days/365.25
    totals = {'买入': defaultdict(float), '卖出': defaultdict(float)}
    for row in csv.DictReader((folder/'ledger.csv').open()):
        side, day = row['action'], row['date']
        amount = float(row['shares'])*float(row['price'])
        if amount <= 0:
            continue
        linear = amount*.0001
        commission = max(linear,5)
        premium = commission-linear
        transfer = amount*.00001
        stamp = amount*.0005 if side=='卖出' else 0
        total = totals[side]
        total['orders'] += 1
        total['turnover_cny'] += amount
        total['commission_cny'] += commission
        total['transfer_cny'] += transfer
        total['stamp_cny'] += stamp
        total['minimum_premium_cny'] += premium
        total['orders_below_50000'] += amount < 50000
        total['normalized_commission'] += commission/previous.get(day,equity[day])
    for total in totals.values():
        total['commission_annualized_bps'] = total.pop('normalized_commission')/years*10000
    return {'years':years,'sides':totals}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exp',type=Path,default=ROOT/'data/experiments/exp_residual_cny')
    ap.add_argument('--labels',default='BASE,CNY50')
    args = ap.parse_args()
    actions = load_actions()
    results = {}
    for label in args.labels.split(','):
        folder = args.exp/'sig'/label
        result = audit(folder,actions)
        result['fees'] = fee_audit(folder)
        result['counts']['remaining_below_50000'] = sum(
            e['remaining_shares']*e['sell_price'] < 50000 for e in result['events'])
        results[label] = result
        print(label,result['counts'],result['fees'])
    (args.exp/'fee_audit.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
