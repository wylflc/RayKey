"""Audit replay copies before recording an explicit code/action migration."""
import copy
import json
from pathlib import Path
import sys
import types
from prepare import EXP, ROOT, digest, save
sys.path.insert(0,str(ROOT/'scripts'))
import shadow_from_origin as new
import shadow_portfolio as sh
BOOK=new.BOOK

def frozen(name):
    path=EXP/'old_inputs/scripts'/f'{name}.py'
    mod=types.ModuleType('oi197_'+name); mod.__file__=str(ROOT/'scripts'/f'{name}.py'); sys.modules[mod.__name__]=mod
    exec(compile(path.read_bytes(),str(path),'exec'),mod.__dict__)
    return mod

def main():
    manifest=json.loads((BOOK/'manifest.json').read_text())
    save('shadow_manifest_before.json',manifest)
    snapshots=[]; supplement={}
    for day,h in sorted(manifest['snapshots'].items()):
        path=BOOK/'snapshots'/f'{day}.json'; assert digest(path)['sha256']==h
        snapshots.append(json.loads(path.read_text()))
    for code,h in manifest['supplemental_prices'].items():
        path=BOOK/'supplement'/f'{code}.json'; assert digest(path)['sha256']==h
        supplement[code]=json.loads(path.read_text())['rows']
    for name,h in manifest.get('price_updates',{}).items():
        path=BOOK/name; assert digest(path)['sha256']==h
        update=json.loads(path.read_text()); supplement[update['code']]=new.merge_prices(supplement.get(update['code'],[]),update['rows'])
    # Apply previous evidenced migrations before forming this turn's OLD arm.
    for name, sha in manifest.get('action_corrections', {}).items():
        path = BOOK/name; assert digest(path)['sha256'] == sha
        snapshots = new.corrected_actions(snapshots, json.loads(path.read_text()))
    import csv
    import corporate_actions as ca
    ca.PRICE_TERMS_PATH = EXP/'price_terms_corrected.csv'
    with (EXP/'actions_corrected.csv').open() as f:
        daily = ca.aggregate_actions(csv.DictReader(f))
    events = {}; notices = {}
    verified = ca.price_overrides()
    for event in daily:
        code, day = event['security_code'], event['ex_dividend_date']
        rule = verified.get((code, day))
        if rule and '2024-01-01' <= day <= snapshots[-1]['date']:
            priced = ca.with_price_terms(event)
            events.setdefault(code,{})[day] = {k:priced[k] for k in (*ca.AMOUNTS,*ca.PRICE_FIELDS)}
            notices.setdefault(code,{})[day] = rule['notice_date']
    correction=dict(issue='OI-197', through=snapshots[-1]['date'], availability='per_event',
                    notice_dates=notices, events=events,
                    evidence='data/experiments/exp_oi197_20260921/price_terms_corrected.csv',
                    evidence_sha256=digest(EXP/'price_terms_corrected.csv')['sha256'],
                    scope='Evidenced action bases on replay copies; original observed quotes/valuations/signals remain archived unchanged.')
    save('shadow_action_correction.json',correction)
    corrected=new.corrected_actions(snapshots,correction)
    old=frozen('shadow_from_origin'); old.bt=frozen('backtest_valuation_strategy')
    outcomes={}
    for name,shares in manifest['scenarios'].items():
        old_result=old.replay(snapshots,supplement,manifest,shares)
        new_result=new.replay(corrected,supplement,manifest,shares)
        stored_states=json.loads((BOOK/name/'states.json').read_text())
        stored_fills=sh.csv_rows((BOOK/name/'fills.csv').read_bytes())
        same_states=old_result[2]==stored_states
        assert same_states, 'Frozen OLD failed to reproduce stored shadow states'
        equality=[a==b for a,b in zip(old_result,new_result)]
        assert all(equality), equality
        outcomes[name]=dict(old_reproduces_stored_states=same_states, old_new_equal=equality,
                            days=len(new_result[0]),fills=len(new_result[1]),last_equity=new_result[0][-1])
    changed=sum(a!=b for a,b in zip(snapshots,corrected))
    save('shadow_validation.json',dict(outcomes=outcomes,original_snapshots=len(snapshots),corrected_copies=changed,
                                      original_snapshots_unchanged=all(digest(BOOK/'snapshots'/f'{day}.json')['sha256']==h for day,h in manifest['snapshots'].items()),
                                      code_before=manifest['code_sha256'],code_after=new.hashes()))
    print(json.dumps(outcomes,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
