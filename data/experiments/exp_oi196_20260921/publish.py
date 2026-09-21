"""Install only verified target blocks after passing Track A; retain original shadow archives."""
import json
import os
import shutil
import sys
from prepare import EXP, ROOT, digest, save
from assemble import FILES, splice
sys.path.insert(0,str(ROOT/'scripts'))
from daily_execution_guard import stamp
import shadow_from_origin as shadow

def main():
    validation=json.loads((EXP/'verification.json').read_text())
    assert validation['track_a_pass'] and validation['zero_negative_cash'] and validation['complete_pairing']
    extracted=json.loads((EXP/'state_extracts.json').read_text())
    raw=ROOT/'data/raw/corporate_actions/a_share_corporate_actions.csv'
    assert digest(raw)==digest(EXP/'old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv')
    # Preserve current small downstream products before rematerializing them.
    paths=['data/processed/a_share_valuation_dossiers.csv','data/processed/a_share_focus_watchlist_l1_l2_valuation.csv',
           'data/processed/a_share_core_valuation_pool.csv','data/processed/daily_execution_publication.json',
           'data/interim/daily_evidence_2026-09-21.json','data/raw/corporate_actions/a_share_corporate_actions.csv.meta.json',
           'data/processed/daily_holdings_tracking.csv','data/interim/daily_execution_2026-09-21.json',
           'data/processed/a_share_holdings.csv','data/processed/portfolio_account_snapshot.csv']
    preserved={}
    for name in paths:
        path=ROOT/name
        if not path.exists():continue
        dest=EXP/'old_inputs'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.exists(): shutil.copyfile(path,dest)
        assert digest(dest)==digest(path),name
        preserved[name]=digest(path)
    save('downstream_before.json',preserved)
    result={}
    for name in FILES:
        target=ROOT/'data/processed'/name
        assert digest(target)['sha256']==extracted['files'][name]['source_sha256'],name
        tmp=target.with_name('.'+name+'.oi196')
        result[name]=splice(target,EXP/'states/new_blocks'/name,tmp,set(extracted['targets']))
        os.replace(tmp,target);result[name]['after']=digest(target)
        print('INSTALLED',name,flush=True)
    tmp=raw.with_name('.'+raw.name+'.oi196');shutil.copyfile(EXP/'actions_corrected.csv',tmp);os.replace(tmp,raw)
    stamp(raw,'2026-09-21',inputs=[EXP/'source_manifest.json',EXP/'repairs.json',ROOT/'data/reference/a_share_action_component_exclusions.csv'])
    result['actions']=digest(raw)
    save('publication.json',dict(job_id=os.getenv('SLURM_JOB_ID'),installed=result))
    before=json.loads((EXP/'shadow_manifest_before.json').read_text())
    book=shadow.BOOK; assert json.loads((book/'manifest.json').read_text())==before
    checked=json.loads((EXP/'shadow_validation.json').read_text());assert checked['code_after']==shadow.hashes()
    assert checked['original_snapshots_unchanged'] and all(all(r['old_new_equal']) for r in checked['outcomes'].values())
    correction='corrections/oi196_actions_20260921.json';migration='migrations/oi196_20260921.json'
    target=book/correction;target.parent.mkdir(exist_ok=True);assert not target.exists()
    shutil.copyfile(EXP/'shadow_action_correction.json',target)
    target=book/migration;target.parent.mkdir(exist_ok=True);assert not target.exists()
    record=dict(issue='OI-196',created_at_beijing=shadow.sh.now(),before_code_sha256=before['code_sha256'],after_code_sha256=shadow.hashes(),
                before_manifest_sha256=digest(EXP/'shadow_manifest_before.json')['sha256'],
                validation='data/experiments/exp_oi196_20260921/shadow_validation.json', validation_sha256=digest(EXP/'shadow_validation.json')['sha256'],
                original_snapshots_unchanged=True, replay_economics_unchanged=True)
    shadow.sh.save(target,record)
    before['code_sha256']=shadow.hashes()
    before.setdefault('code_migrations',{})[migration]=digest(target)['sha256']
    before.setdefault('action_corrections',{})[correction]=digest(book/correction)['sha256']
    shadow.sh.save(book/'manifest.json',before)
    shadow.load()
    print('Installed explicit shadow migration; original archives preserved',flush=True)

if __name__=='__main__':main()
