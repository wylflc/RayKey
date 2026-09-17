"""Offline illustration on September 17 inputs; never publishes or writes holdings."""
import copy
import csv
import hashlib
import inspect
import json
from pathlib import Path
from engine import EXP, ROOT, repeat_candidates
import screen_daily_volume_price_signals as s
from pv_ratio import load_model_bands
from a_share_signal_dates import evidence_iso_for_signal

DAY = '2026-09-17'


def main():
    pub = json.loads((ROOT / 'data/processed/daily_execution_publication.json').read_text())
    paths = list(pub['inputs']) + list(pub['outputs'])
    hashes = {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    with (ROOT / 'data/processed/daily_buy_candidates.csv').open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ('close','mark_close','ma20','ma60','model_pv','hold_pv','model_intrinsic_value','hold_intrinsic_value','quality_score'):
            if r.get(k): r[k]=float(r[k])
        r['tradable']=str(r.get('tradable')).lower()=='true'
    s.attach_model_pv(rows,load_model_bands(s.DEFAULT_HOLD_BANDS,evidence_iso_for_signal(DAY)),DAY,s._default_rf(DAY),prefix='hold')
    holdings=s.load_holdings_detail()
    source=inspect.getsource(s.section93_execution_plan)
    loop='    if funds is not None and valuation_complete:\n        for cand in eligible:\n'
    assert source.count(loop)==1
    scope=dict(s.__dict__)
    scope['_repeat_swap_candidates']=repeat_candidates
    source=source.replace(loop,'    if funds is not None and valuation_complete:\n        for cand in _repeat_swap_candidates(eligible, lambda: len(sells)):\n')
    exec(compile(source,'offline_today_repeat','exec'),scope)
    # Correlations only report; bypass network-free missing history in this illustration.
    scope['corr_252']=lambda *args:None
    original_corr=s.corr_252
    s.corr_252=lambda *args:None
    eb,cap=s.equity_bond_signal(DAY)
    results={}
    try:
        for arm,run in [('BASE',s.section93_execution_plan),('REPEAT',scope['section93_execution_plan'])]:
            result=run(copy.deepcopy(rows),2632343.18,-70356.73,copy.deepcopy(holdings),
                s.load_blocked_codes(s.DEFAULT_REVIEW_QUEUE),s.load_tactical_gate_codes(s.SEC93_TIERS),
                s.load_worth_attention_codes(),{},sell_counters={},exposure_cap=cap)
            results[arm]=dict(sells=result['sells'],buys=result['plan'],remaining_funds=result['cash'],
                              swap_stop_reason=result['swap_stop_reason'])
    finally:
        s.corr_252=original_corr
    assert [r['security_code'] for r in results['BASE']['sells']]==['002714']
    assert [r['security_code'] for r in results['REPEAT']['sells']]==['002714','002128']
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    (EXP/'today_counterfactual.json').write_text(json.dumps(dict(signal_date=DAY,
        illustration_only=True,production_files_unchanged=True,fees_included=False,results=results),ensure_ascii=False,indent=2)+'\n')
    print({arm:{'sell':[(r['security_code'],r['sell_shares']) for r in x['sells']],
                      'buy':[(r['security_code'],r['shares']) for r in x['buys']],
                      'funds':x['remaining_funds']} for arm,x in results.items()})


if __name__=='__main__': main()
