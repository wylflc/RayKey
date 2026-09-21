"""Install validated native target blocks; retain every frozen old full input."""
import json
import os
from prepare import EXP, ROOT, digest, save, FILES
from assemble import splice


def main():
    v=json.loads((EXP/'verification.json').read_text())
    assert v['track_a_pass'] and v['zero_negative_cash'] and v['complete_pairing']
    assert json.loads((EXP/'diagnostics_validation.json').read_text())['status']=='passed'
    assert not json.loads((EXP/'classification.json').read_text())['unexplained']
    extracted=json.loads((EXP/'state_extracts.json').read_text())
    # Check all input hashes before any production file is replaced.
    for name,info in extracted['files'].items():
        assert digest(ROOT/'data/processed'/name)['sha256']==info['source_sha256'], name
        assert digest(EXP/'old_inputs/data/processed'/name)['sha256']==info['source_sha256'], name
    result={}
    for name in FILES:
        target=ROOT/'data/processed'/name;tmp=target.with_name('.'+name+'.oi198')
        result[name]=splice(target,EXP/'states/new_blocks'/name,tmp,set(extracted['targets']))
        os.replace(tmp,target);result[name]['after']=digest(target)
        print('INSTALLED',name,flush=True)
    save('publication.json',dict(job_id=os.getenv('SLURM_JOB_ID'),installed=result,
         native_production_bridge=True,old_full_inputs_retained=True))


if __name__=='__main__':main()
