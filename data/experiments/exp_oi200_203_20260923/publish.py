"""Install the NEW full rebuild as the seven production state files; frozen old copies stay in old_inputs.

Preconditions (fail closed): CONTROL reproduces the stored states apart from OI-202 output columns and listed input
updates; NEW track-A verdict recorded; buy line retained under the 0.2pp tolerance, or the user's ruling recorded in
`user_ruling.json` (§12.1 第 8 款)."""
import os
import shutil

from common import EXP, ROOT, STATE_FILES, digest, load, save


def main():
    control = load('control_validation.json')
    assert all(not r['changed_fields'] and not r['only_in_left'] and not r['only_in_right'] for r in control.values()), \
        'CONTROL must reproduce stored states except OI-202 output columns'
    verification = load('verification.json')
    diag = load('diagnostics_validation.json')
    ruling = load('user_ruling.json') if (EXP / 'user_ruling.json').exists() else {}
    assert verification['track_a_pass'] or ruling.get('adopt_despite_guardrail'), 'track-A guardrail: needs user ruling'
    assert diag['buy_line']['NEW']['retained'] or ruling.get('buy_line'), 'buy line outside tolerance: needs user ruling'
    before = load('before_manifest.json')
    for name in STATE_FILES:
        assert digest(ROOT / 'data/processed' / name) == before['states'][name]['source'], name
    installed = {}
    for name in STATE_FILES:
        target = ROOT / 'data/processed' / name
        tmp = target.with_name('.' + name + '.oi200')
        shutil.copyfile(EXP / 'states/NEW_build' / name, tmp)
        os.replace(tmp, target)
        installed[name] = dict(before=before['states'][name]['source'], after=digest(target))
        print('INSTALLED', name, flush=True)
    save('publication.json', dict(job_id=os.getenv('SLURM_JOB_ID'), installed=installed, old_full_inputs_retained=True,
                                  ruling=ruling))


if __name__ == '__main__':
    main()
