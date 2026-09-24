"""v4.207 研究增长落地后按同一信号日重发（§7.3 当晚生效、§9.1 第 5 步），并核对爱玛三份池带与执行清单。"""
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_execution_guard as guard  # noqa: E402

SIGNAL, CODE = '2026-09-24', '603529'


def read(path):
    with path.open(encoding='utf-8-sig') as fh:
        return list(csv.DictReader(fh))


def main():
    account = next(r for r in read(ROOT / 'data/processed/portfolio_account_snapshot.csv') if r['as_of'] == SIGNAL)
    subprocess.run([sys.executable, str(ROOT / 'scripts/screen_daily_volume_price_signals.py'), '--as-of', SIGNAL,
                    '--review-queue', 'data/interim/a_share_report_update_queue.csv',
                    '--model-bands', 'data/processed/a_share_pool_model_bands_adopted.csv',
                    '--hold-bands', 'data/processed/a_share_pool_model_bands_hold.csv',
                    '--nav', account['net_assets_cny'], '--funds', '0', '--cash', account['cash_cny'] or '0',
                    '--debt', account['margin_debt_cny'], '--workers', '16'], cwd=ROOT, check=True)
    guard.verify_publication(ROOT / 'data/processed/daily_execution_publication.json', SIGNAL)
    guard.verify_strategy_columns(SIGNAL)
    g0 = json.loads((EXP / 'register.json').read_text())['g0']
    sides = {}
    for name in ('adopted', 'b2', 'hold'):
        band = next(r for r in read(ROOT / f'data/processed/a_share_pool_model_bands_{name}.csv') if r['security_code'] == CODE)
        assert band['g0'] == f'{g0:.4f}' and band['model_g0'], (name, band['g0'], band.get('model_g0'))
        sides[name] = dict(iv=float(band['intrinsic_value']), g0=band['g0'], model_g0=band['model_g0'])
    scen = next(s for s in json.loads((EXP / 'scenarios.json').read_text())['scenarios'] if s['scenario'].startswith('起点移到 2022'))
    assert abs(sides['adopted']['iv'] - scen['V']) < 0.02, (sides['adopted']['iv'], scen['V'])
    queue = read(ROOT / 'data/interim/a_share_report_update_queue.csv')
    plans = {n: len(read(ROOT / 'data/processed' / n)) for n in ('daily_entry_plan.csv', 'daily_sell_plan.csv')}
    out = dict(checked_at_utc=datetime.now(timezone.utc).isoformat(), sides=sides, scenario_v=scen['V'], queue_rows=len(queue), plans=plans)
    (EXP / 'final_validation.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print('FINAL OK', json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    main()
