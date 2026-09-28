"""Install the ruled arm's full rebuild as the seven production state files; frozen old copies stay in old_inputs.

Preconditions (fail closed): CONTROL reproduces the stored states; the user's ruling is recorded in `user_ruling.json` (state arm,
buy line whenever the arm's old-line share is outside the 0.2pp tolerance, and adopt_despite_guardrail when Track A fails);
stored states are still the frozen ones."""
import os
import shutil

from common import EXP, ROOT, STATE_FILES, digest, load, save


def main():
    for name, r in load('control_validation.json').items():
        assert not r['changed_fields'], (name, 'CONTROL drift', r['changed_fields'])
        assert not (r['unmatched_left_codes'] or r['unmatched_right_codes'] or r['only_in_left'] or r['only_in_right']), name
    ruling = load('user_ruling.json')
    arm = ruling['state_arm']
    assert arm == ruling.get('tested_arm', arm) == 'H2', ruling
    verification, align = load('verification.json'), load('align_check.json')['arms'][arm]
    assert verification['zero_negative_cash']
    assert align['retained'] or abs(ruling.get('buy_line', 0) - align['line']) < 1e-9, 'buy line must be the aligned solution'
    before = load('before_manifest.json')
    for name in STATE_FILES:
        assert digest(ROOT / 'data/processed' / name) == before['states'][name]['source'], name
    installed = {}
    for name in STATE_FILES:
        target = ROOT / 'data/processed' / name
        tmp = target.with_name('.' + name + '.v4215')
        shutil.copyfile(EXP / 'states' / f'{arm}_build' / name, tmp)
        os.replace(tmp, target)
        installed[name] = dict(before=before['states'][name]['source'], after=digest(target))
        print('INSTALLED', name, flush=True)
    save('publication.json', dict(job_id=os.getenv('SLURM_JOB_ID'), arm=arm, installed=installed, old_full_inputs_retained=True,
                                  ruling=ruling))


if __name__ == '__main__':
    main()
