"""Rebuild current pool in staging; compare with the frozen production rows."""
import json
import subprocess
import sys
from prepare import EXP, ROOT, read, save, digest


def main():
    stage=EXP/'states/current';stage.mkdir(exist_ok=True)
    states=EXP/'states/NEW'
    for suffix, output, state in (('', 'adopted','adopted'),('_b2','b2','b2')):
        out=stage/f'a_share_pool_model_bands_{output}.csv'
        subprocess.run([sys.executable,str(ROOT/'scripts/build_pool_model_bands.py'),'--signal-date','2026-09-21',
            '--bands',str(states/f'roic_bands{suffix}.csv'),'--states',str(states/f'a_share_daily_states_{state}.csv'),
            '--out',str(out)],check=True)
        subprocess.run([sys.executable,str(ROOT/'scripts/apply_forecast_band_overlay.py'),
            '--signal-date','2026-09-21','--bands',str(out)],check=True)
    subprocess.run([sys.executable,str(ROOT/'scripts/build_hold_model_bands.py'),'--signal-date','2026-09-21',
        '--base',str(stage/'a_share_pool_model_bands_adopted.csv'),'--b2',str(stage/'a_share_pool_model_bands_b2.csv'),
        '--out',str(stage/'a_share_pool_model_bands_hold.csv')],check=True)
    differences={}
    for name in ('adopted','b2','hold'):
        filename=f'a_share_pool_model_bands_{name}.csv'
        old={r['security_code']:r for r in read(EXP/'old_inputs/data/processed'/filename)}
        new={r['security_code']:r for r in read(stage/filename)}
        assert old.keys()==new.keys(), name
        differences[name]={c:{k:[old[c].get(k,''),v] for k,v in new[c].items() if v!=old[c].get(k,'')}
                           for c in old if old[c]!=new[c]}
    save('current_changes.json',differences)
    print('CURRENT CHANGES', {s:len(v) for s,v in differences.items()},flush=True)


if __name__=='__main__':main()
