"""Final checks: installed states, pool/dossier/core consistency, unchanged account and holdings, execution credential."""
import json
from datetime import datetime, timezone

from common import EXP, ROOT, STATE_FILES, digest, load, read, save
import sys
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_execution_guard as guard

SIGNAL = '2026-09-23'


def main():
    guard.verify_publication(ROOT / 'data/processed/daily_execution_publication.json', SIGNAL)
    guard.verify_strategy_columns(SIGNAL)
    publication = load('publication.json')
    for name in STATE_FILES:
        assert digest(ROOT / 'data/processed' / name) == publication['installed'][name]['after'], name
    unchanged = {n: digest(ROOT / 'data/processed' / n) == digest(EXP / 'old_inputs/data/processed' / n)
                 for n in ('a_share_holdings.csv', 'portfolio_account_snapshot.csv')}
    assert all(unchanged.values()), unchanged
    for name in ('adopted', 'b2', 'hold'):
        f = f'a_share_pool_model_bands_{name}.csv'
        live = {r['security_code']: r.get('intrinsic_value') for r in read(ROOT / 'data/processed' / f)}
        staged = {r['security_code']: r.get('intrinsic_value') for r in read(EXP / 'states/current' / f)}
        assert live == staged, f
    model = {r['security_code']: r for r in read(ROOT / 'data/processed/a_share_pool_model_bands_adopted.csv')}
    dossiers = {r['security_code']: r for r in read(ROOT / 'data/processed/a_share_valuation_dossiers.csv')}
    core = {r['security_code']: r for r in read(ROOT / 'data/processed/a_share_core_valuation_pool.csv')}
    checked = 0
    for c, r in model.items():
        if not r.get('intrinsic_value') or r.get('roic_path') == 'bank_divspread':
            continue
        iv = float(r['intrinsic_value'])
        for key, target, coef in (('band_low', 'fair_price_low', .90), ('band_high', 'fair_price_high', 1.10)):
            assert abs(iv * coef - float(dossiers[c][key])) < .011, (c, 'dossier')
            assert abs(float(dossiers[c][key]) - float(core[c][target])) < .011, (c, 'core')
        checked += 1
    plans = {n: len(read(ROOT / 'data/processed' / n)) for n in ('daily_entry_plan.csv', 'daily_sell_plan.csv')}
    save('final_validation.json', dict(status='passed', checked_at_utc=datetime.now(timezone.utc).isoformat(),
                                       unchanged=unchanged, bands_checked=checked, plans=plans,
                                       publication=digest(ROOT / 'data/processed/daily_execution_publication.json')))
    print('FINAL OK', checked, plans)


if __name__ == '__main__':
    main()
