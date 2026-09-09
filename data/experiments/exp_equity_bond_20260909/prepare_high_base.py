"""Freeze the preregistered low-only financing overlay; retain first-stage sources."""
import json
from pathlib import Path
import shlex
import shutil
import sys
EXP=Path(__file__).resolve().parent/'high_base'
ROOT=EXP.parents[3]
sys.path.insert(0,str(EXP.parent))
from prepare import fingerprint


def save(name,value):
    (EXP/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    EXP.mkdir(exist_ok=True)
    first=json.loads((EXP.parent/'manifest.json').read_text())
    assert fingerprint({ROOT/p for p in first['inputs']})==first['inputs']
    configs=(EXP.parent/'configs.txt').read_text().splitlines()
    base=next(s for s in configs if s.startswith('BASE|'))
    lines=[base];grid=[{'arm':'BASE','kind':'baseline'}]
    for line in configs:
        arm,extra=line.split('|',1)
        if arm.startswith(('EBQ','EBS','EBCR')):
            new=arm.replace('EBQ','EBDQ').replace('EBS','EBDS').replace('EBCR','EBDC')
            lines.append(new+'|'+extra)
            grid.append({'arm':new,'kind':'credit' if arm.startswith('EBCR') else 'percentile' if arm.startswith('EBQ') else 'spread'})
    (EXP/'configs.txt').write_text('\n'.join(lines)+'\n')
    save('grid.json',grid)
    shutil.copyfile(EXP.parent/'baseline_before.csv',EXP/'baseline_before.csv')
    protected={ROOT/p for p in first['inputs']}|{EXP/'configs.txt',EXP/'grid.json',EXP/'baseline_before.csv'}
    protected|={EXP.parent/name for name in ('prepare_high_base.py','run_high_base.py','scan_high_base.py','high_base_engine.py','preregister_high_base.md')}
    first['inputs']=fingerprint(protected);first['candidate_count']=7;first['known_nonbase_controls']=0
    save('manifest.json',first)
    save('prepare_verification.json',{'inputs_unchanged':True})
    print('HIGH-BASE PREPARE COMPLETE: 7 new candidates; same source fingerprints.',flush=True)


if __name__=='__main__':main()
