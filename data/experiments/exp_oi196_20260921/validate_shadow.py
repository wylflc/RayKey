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
    mod=types.ModuleType('oi196_'+name); mod.__file__=str(ROOT/'scripts'/f'{name}.py'); sys.modules[mod.__name__]=mod
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
    repairs=json.loads((EXP/'repairs.json').read_text()); events={}
    for event in repairs['new_daily_events']:
        if event['ex_dividend_date'] >= '2024-01-01':
            events.setdefault(event['security_code'],{})[event['ex_dividend_date']]={k:event[k] for k in ('cash_per_share','share_ratio','rights_ratio','rights_price')}
    correction=dict(issue='OI-196', through=snapshots[-1]['date'], known_by=snapshots[0]['date'],events=events,
                    evidence='data/experiments/exp_oi196_20260921/repairs.json', evidence_sha256=digest(EXP/'repairs.json')['sha256'],
                    scope='Replay copies of all_actions only; original quotes, valuations, snapshots and real account remain archived unchanged.')
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
