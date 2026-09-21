"""Final input, valuation, account, execution and immutable shadow checks."""
import json
from datetime import datetime, timezone
from prepare import EXP, ROOT, read, digest, save, FILES
import daily_execution_guard as guard
import shadow_from_origin as shadow
from classify import differences


def main():
    guard.verify_publication(ROOT/'data/processed/daily_execution_publication.json','2026-09-21')
    guard.verify_strategy_columns('2026-09-21')
    publication=json.loads((EXP/'publication.json').read_text())
    extracted=json.loads((EXP/'state_extracts.json').read_text())
    for name in FILES:
        assert digest(ROOT/'data/processed'/name)==publication['installed'][name]['after'], name
        assert digest(EXP/'old_inputs/data/processed'/name)['sha256']==extracted['files'][name]['source_sha256'], name
    unchanged={}
    for name in ('a_share_holdings.csv','portfolio_account_snapshot.csv'):
        unchanged[name]=digest(ROOT/'data/processed'/name)==digest(EXP/'old_inputs/data/processed'/name)
        assert unchanged[name],name
    for name in ('adopted','b2','hold'):
        filename=f'a_share_pool_model_bands_{name}.csv'
        assert read(ROOT/'data/processed'/filename)==read(EXP/'states/current'/filename),filename
    current={r['security_code']:r for r in read(ROOT/'data/processed/daily_buy_candidates.csv')}
    old={r['security_code']:r for r in read(EXP/'old_inputs/data/processed/daily_buy_candidates.csv')}
    assert current.keys()==old.keys()
    assert all(r['trade_date']=='2026-09-21' and r['signal_state']!='data_error' for r in current.values())
    assert all(r['close']==old[c]['close'] for c,r in current.items())
    changes={c:differences(old[c],r) for c,r in current.items() if differences(old[c],r)}
    save('candidate_changes.json',changes)
    model={r['security_code']:r for r in read(ROOT/'data/processed/a_share_pool_model_bands_adopted.csv')}
    dossiers={r['security_code']:r for r in read(ROOT/'data/processed/a_share_valuation_dossiers.csv')}
    core={r['security_code']:r for r in read(ROOT/'data/processed/a_share_core_valuation_pool.csv')}
    for c,r in model.items():
        if not current[c]['model_intrinsic_value']:
            assert not dossiers[c]['band_low'] and not core[c]['fair_price_low'],c
            continue
        iv=float(r['intrinsic_value']);live_iv=iv
        if r.get('roic_path')=='bank_divspread':
            from screen_daily_volume_price_signals import resolve_live_band
            live,_=resolve_live_band(c,current[c]['security_name'],'2026-09-21',model);live_iv=live['intrinsic_value']
        assert abs(float(current[c]['model_intrinsic_value'])-live_iv)<.011,(c,'scan')
        for key,target,coef in (('band_low','fair_price_low',.90),('band_high','fair_price_high',1.10)):
            assert abs(iv*coef-float(dossiers[c][key]))<.011,(c,'dossier')
            assert abs(float(dossiers[c][key])-float(core[c][target]))<.011,(c,'core')
    manifest,snapshots,supplement=shadow.load()
    before=json.loads((EXP/'old_inputs/data/processed/shadow_portfolio/since_20260828/manifest.json').read_text())
    assert manifest==before
    assert all(digest(shadow.BOOK/'snapshots'/f'{day}.json')['sha256']==h for day,h in manifest['snapshots'].items())
    checks=dict(historical_native_files=len(FILES),old_full_inputs_retained=True,current_models_match_staging=True,
        current_candidates=len(current),unchanged_account_and_holdings=unchanged,unchanged_closes=True,
        original_shadow_snapshots_preserved=len(snapshots),shadow_manifest_unchanged=True,
        buy_sell_rows={n:len(read(ROOT/'data/processed'/n)) for n in ('daily_entry_plan.csv','daily_sell_plan.csv')})
    save('final_validation.json',dict(status='passed',checked_at_utc=datetime.now(timezone.utc).isoformat(),checks=checks,
        publication=digest(ROOT/'data/processed/daily_execution_publication.json')))
    print(json.dumps(checks,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
