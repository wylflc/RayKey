"""Execute only the cost follow-up frozen in preregister.md, if stage-one passes."""
import json
from common import EXP, save, write, read
from run import batch, validate_groups


def main():
    passing=json.loads((EXP/'followup.json').read_text())['passing_arms']
    if not passing:
        save('cost_followup.json',dict(passing_arms=[],additional_paths=0,
            reason='No stage-one candidate passed clause 2; preregistered center 30bp stress remains reported.'))
        return
    manifest=json.loads((EXP/'manifest.json').read_text())
    verify=json.loads((EXP/'verification.json').read_text())
    sets=json.loads((EXP/'winner_sets.json').read_text())
    a=sets[passing[0]]['A']
    needs={'full':([],set(passing)), 'A':(a,set(passing))}
    for group,meta in verify['union_groups'].items():
        arms=set(meta['candidates'])&set(passing)
        if arms:needs[group]=(meta['codes'],arms)
    rows=read(EXP/'summary_rows.csv')
    old={(r['group'],r['arm'],r['start'],int(r['bp'])) for r in rows}
    new=[]
    for group,(excluded,arms) in needs.items():
        for bp in (10,20,30):
            data=batch(group,['BASE',*sorted(arms)],excluded,manifest,12,bp)
            new += [r for r in data if (r['group'],r['arm'],r['start'],int(r['bp'])) not in old]
    allrows=[dict(r,bp=int(r['bp'])) for r in rows+new]
    validate_groups(allrows);write('summary_rows.csv',allrows)
    save('cost_followup.json',dict(passing_arms=passing,additional_paths=len(new)))


if __name__=='__main__':main()
