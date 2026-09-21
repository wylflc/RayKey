"""Final publication, account and valuation checks; no mutation of execution inputs."""
import csv
import json
import sys
from datetime import datetime, timezone
from prepare import EXP, ROOT, digest, read, save
sys.path.insert(0,str(ROOT/'scripts'))
import corporate_actions as actions
import daily_execution_guard as guard
import shadow_from_origin as shadow

def main():
    publication=guard.verify_publication(ROOT/'data/processed/daily_execution_publication.json','2026-09-21')
    guard.verify_strategy_columns('2026-09-21')
    checks={}
    for name in ('a_share_holdings.csv','portfolio_account_snapshot.csv'):
        checks[name]=digest(ROOT/'data/processed'/name)==digest(EXP/'old_inputs/data/processed'/name)
        assert checks[name],name
    for name in ('daily_entry_plan.csv','daily_sell_plan.csv'):
        checks[name]=len(read(ROOT/'data/processed'/name)); assert checks[name]==0
    candidates=read(ROOT/'data/processed/daily_buy_candidates.csv');old=read(EXP/'old_inputs/data/processed/daily_buy_candidates.csv')
    current={r['security_code']:r for r in candidates};old={r['security_code']:r for r in old}
    assert len(current)==len(candidates)==181 and current.keys()==old.keys()
    assert all(r['trade_date']=='2026-09-21' and r['signal_state']!='data_error' for r in candidates)
    assert all(current[c]['close']==old[c]['close'] for c in current)
    tracking=read(ROOT/'data/processed/daily_holdings_tracking.csv')
    old_tracking={r['security_code']:r for r in read(EXP/'old_inputs/data/processed/daily_holdings_tracking.csv')}
    for r in tracking:
        o=old_tracking[r['security_code']]
        for key in ('current_shares','close','entry_stop_price','stop_line','stop_hit'):
            assert r[key]==o[key],(r['security_code'],key,r[key],o[key])
    checks['holding_tracking_unchanged']=True
    components=read(ROOT/'data/raw/corporate_actions/a_share_corporate_actions.csv')
    events=actions.event_map(components)
    assert len(components)==54637
    assert events['300760']['2026-05-28'][0]==1.56
    assert events['300760']['2025-05-29'][0]==1.97
    assert events['600080']['1997-08-19'][1]==.6
    model={r['security_code']:r for r in read(ROOT/'data/processed/a_share_pool_model_bands_adopted.csv')}
    dossiers={r['security_code']:r for r in read(ROOT/'data/processed/a_share_valuation_dossiers.csv')}
    core={r['security_code']:r for r in read(ROOT/'data/processed/a_share_core_valuation_pool.csv')}
    for c,r in model.items():
        if current[c]['model_intrinsic_value']:
            from build_historical_valuation_bands import BAND_LOW_COEF, BAND_HIGH_COEF
            iv=float(r['intrinsic_value'])
            expected_live=iv
            if r.get('roic_path')=='bank_divspread':
                from screen_daily_volume_price_signals import resolve_live_band
                live,_=resolve_live_band(c,current[c]['security_name'],'2026-09-21',model)
                expected_live=live['intrinsic_value']
            assert abs(float(current[c]['model_intrinsic_value'])-expected_live)<.011,(c,'scanner')
            # Display bands are rebuilt at IV × [0.90, 1.10]; historical price
            # affine adjustment preserves the midpoint, not that display width.
            assert abs((float(r['band_low'])+float(r['band_high']))/2-iv)<.011,(c,'model midpoint')
            for key,target,coef in (('band_low','fair_price_low',BAND_LOW_COEF),('band_high','fair_price_high',BAND_HIGH_COEF)):
                assert abs(iv*coef-float(dossiers[c][key]))<.011,(c,key,'dossier')
                assert abs(float(dossiers[c][key])-float(core[c][target]))<.011,(c,key,'core')
        else:
            assert not dossiers[c]['band_low'] and not core[c]['fair_price_low'],(c,'stale/unvaluable')
    manifest,snapshots,supplement=shadow.load()
    before=json.loads((EXP/'shadow_manifest_before.json').read_text())
    assert before['snapshots']==manifest['snapshots']
    checks.update(candidates=len(candidates),action_components=len(components),original_shadow_snapshots_preserved=len(snapshots),
                  valuation_pool_rows=len(core),buy_sell_plans_unchanged=True,
                  mindray={k:current['300760'][k] for k in ('close','model_intrinsic_value','model_pv','ma20','ma60')},
                  jobs=dict(audit='26974214',states='26974556',backtest='26974721',publish='26974754',scan='26974807',shadow='26974980'))
    save('final_validation.json',dict(status='passed',checked_at_utc=datetime.now(timezone.utc).isoformat(),checks=checks,
                                     publication=digest(ROOT/'data/processed/daily_execution_publication.json')))
    print(json.dumps(checks,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
