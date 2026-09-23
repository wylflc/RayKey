"""Install the ruled arm's full rebuild as the seven production state files; frozen old copies stay in old_inputs.

Preconditions (fail closed): CONTROL reproduces the stored states apart from the renamed label column; the user's ruling
is recorded in `user_ruling.json` (state arm, and buy line whenever the arm's old-line share is outside the 0.2pp tolerance).
When the installed arm is a rebuild of the tested arm (`tested_arm`), `land_verify.json` must show they differ only in output columns."""
import os
import shutil

from common import EXP, ROOT, STATE_FILES, digest, load, save


def main():
    for name, r in load('control_validation.json').items():
        assert not r['changed_fields'], (name, 'CONTROL drift outside the label column', r['changed_fields'])
        assert not (r['unmatched_left_codes'] or r['unmatched_right_codes'] or r['only_in_left'] or r['only_in_right']), name
    ruling = load('user_ruling.json')
    arm, tested = ruling['state_arm'], ruling.get('tested_arm', ruling['state_arm'])
    verification, align = load('verification.json'), load('align_check.json')['arms'][tested]
    if arm != tested:
        check = load('land_verify.json')
        assert check['pass'] and (check['arm'], check['tested_arm']) == (arm, tested), 'landing rebuild differs beyond output columns'
    assert verification['track_a_pass'] or ruling.get('adopt_despite_guardrail'), 'track-A guardrail: needs user ruling'
    assert align['retained'] or ruling.get('buy_line'), 'buy line outside tolerance: needs user ruling'
    before = load('before_manifest.json')
    for name in STATE_FILES:
        assert digest(ROOT / 'data/processed' / name) == before['states'][name]['source'], name
    installed = {}
    for name in STATE_FILES:
        target = ROOT / 'data/processed' / name
        tmp = target.with_name('.' + name + '.oi204')
        shutil.copyfile(EXP / 'states' / f'{arm}_build' / name, tmp)
        os.replace(tmp, target)
        installed[name] = dict(before=before['states'][name]['source'], after=digest(target))
        print('INSTALLED', name, flush=True)
    save('publication.json', dict(job_id=os.getenv('SLURM_JOB_ID'), arm=arm, installed=installed, old_full_inputs_retained=True,
                                  ruling=ruling))


if __name__ == '__main__':
    main()
