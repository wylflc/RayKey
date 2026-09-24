"""Final checks: installed states, pool/dossier/core consistency, unchanged account and holdings, execution credential."""
import json
import os
from datetime import datetime, timezone

from common import EXP, ROOT, STATE_FILES, digest, load, read, save, unchanged_since_freeze
import sys
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_execution_guard as guard

SIGNAL = os.environ.get('EXP_SIGNAL', '2026-09-24')
AIMA = '603529'   # 研究数随落地修订为 16.40 亿，不与按 14.80 暂存的 R 当前池比，另核研究口径 V


def main():
    guard.verify_publication(ROOT / 'data/processed/daily_execution_publication.json', SIGNAL)
    guard.verify_strategy_columns(SIGNAL)
    publication = load('publication.json')
    tested = publication['ruling'].get('tested_arm', publication['arm'])
    for name in STATE_FILES:
        assert digest(ROOT / 'data/processed' / name) == publication['installed'][name]['after'], name
    unchanged = {n: unchanged_since_freeze('data/processed/' + n) for n in ('a_share_holdings.csv', 'portfolio_account_snapshot.csv')}
    assert all(unchanged.values()), unchanged
    for name in ('adopted', 'b2', 'hold'):
        f = f'a_share_pool_model_bands_{name}.csv'
        live = {r['security_code']: r.get('intrinsic_value') for r in read(ROOT / 'data/processed' / f)}
        staged = {r['security_code']: r.get('intrinsic_value') for r in read(EXP / 'states/current' / tested / f)}
        assert live.pop(AIMA) and staged.pop(AIMA) and live == staged, f
    aima = next(r for r in read(ROOT / 'data/processed/a_share_pool_model_bands_adopted.csv') if r['security_code'] == AIMA)
    applied = load('aima_research_applied.json')
    assert aima['research_nopat_yi'] == f"{applied['research']:.2f}" and abs(float(aima['intrinsic_value']) - applied['v']) < 0.01, aima['intrinsic_value']
    model = {r['security_code']: r for r in read(ROOT / 'data/processed/a_share_pool_model_bands_adopted.csv')}
    dossiers = {r['security_code']: r for r in read(ROOT / 'data/processed/a_share_valuation_dossiers.csv')}
    core = {r['security_code']: r for r in read(ROOT / 'data/processed/a_share_core_valuation_pool.csv')}
    import csv, io, subprocess
    head = csv.DictReader(io.StringIO(subprocess.check_output(['git', 'show', 'HEAD:data/processed/a_share_valuation_dossiers.csv'], cwd=ROOT, text=True)))
    unvaluable = {c for c, r in dossiers.items() if r.get('band_derivation') == 'model_unvaluable'}
    before = {r['security_code'] for r in head if r.get('band_derivation') == 'model_unvaluable'}
    assert unvaluable & set(model) == before & set(model), 'pool unvaluable set changed'   # 池外档案随新口径变化，只记录
    off_pool = dict(entered=sorted(unvaluable - before - set(model)), left=sorted(before - unvaluable - set(model)))
    checked = 0
    for c, r in model.items():
        if not r.get('intrinsic_value') or r.get('roic_path') == 'bank_divspread' or c in unvaluable:
            continue
        iv = float(r['intrinsic_value'])
        for key, target, coef in (('band_low', 'fair_price_low', .90), ('band_high', 'fair_price_high', 1.10)):
            assert abs(iv * coef - float(dossiers[c][key])) < .011, (c, 'dossier')
            assert abs(float(dossiers[c][key]) - float(core[c][target])) < .011, (c, 'core')
        checked += 1
    plans = {n: len(read(ROOT / 'data/processed' / n)) for n in ('daily_entry_plan.csv', 'daily_sell_plan.csv')}
    save('final_validation.json', dict(status='passed', checked_at_utc=datetime.now(timezone.utc).isoformat(), aima_iv=float(aima['intrinsic_value']),
                                       unchanged=unchanged, bands_checked=checked, pool_unvaluable=sorted(unvaluable & set(model)), off_pool_unvaluable_changes=off_pool, plans=plans,
                                       publication=digest(ROOT / 'data/processed/daily_execution_publication.json')))
    print('FINAL OK', checked, plans)


if __name__ == '__main__':
    main()
