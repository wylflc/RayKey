"""Pair all preregistered fields/windows and report mechanism/cost guardrails."""
import contextlib
import csv
import json
import statistics as st
import sys
from pathlib import Path
EXP=Path(__file__).resolve().parents[1]
ROOT=EXP.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import sweep_backtest_configs as sw


def save(name,value):
    (EXP/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def read(path):
    with path.open() as f:return list(csv.DictReader(f))


def numeric(r):
    return {**{k:sw._field_value(r,k) for k in sw.FIELDS},sw.WIN5_KEY:sw.parse_window_series(r[sw.WIN5_KEY])}


def main():
    complete=json.loads((EXP/'completed.json').read_text());assert complete['unchanged_inputs']
    rows=read(EXP/'summary_rows.csv')
    winners=json.loads((EXP/'winners.json').read_text())
    pairs=[];checks=[]
    for bp in (0,10,20,30):
        for group in ('full','A','U'):
            source='A' if group=='U' and winners['A']==winners['U'] else group
            selected=[r for r in rows if r['group']==source and int(r['bp'])==bp]
            arms={a:{r['start']:numeric(r) for r in selected if r['arm']==a} for a in ('BASE','CONF')}
            defects=sw.pairing_defects(arms,'CONF','BASE',sw.DEFAULT_STARTS,f'{group}:{bp}')
            assert not defects,defects
            nav_equal=0
            for start in sw.DEFAULT_STARTS:
                n,b=arms['CONF'][start],arms['BASE'][start]
                p=dict(group=group,bp=bp,start=start,
                       P_pp=100*sw.start_delta(n,b,sw.WIN5_KEY),CAGR_pp=100*sw.start_delta(n,b,'年化'),
                       P25_pp=100*sw.start_delta(n,b,'滚动5年年化P25'),DD5_pp=100*sw.start_delta(n,b,'滚动5年回撤中位'),
                       MDD_pp=100*sw.start_delta(n,b,'最大回撤'),negative_flip=sw.neg_window_flip(n,b),
                       min_ratio_delta=n['最低担保比例']-b['最低担保比例'],forced_delta=n['强平次数']-b['强平次数'])
                pairs.append(p)
                pair=[next(r for r in selected if r['arm']==a and r['start']==start) for a in ('BASE','CONF')]
                nav_equal+=int((EXP/'nav'/f"{pair[0]['tag']}.csv").read_bytes()==(EXP/'nav'/f"{pair[1]['tag']}.csv").read_bytes())
            current=[r for r in pairs if r['group']==group and r['bp']==bp]
            checks.append(dict(group=group,bp=bp,**{k:st.median(r[k] for r in current) for k in ('P_pp','CAGR_pp','P25_pp','DD5_pp','MDD_pp','min_ratio_delta')},
                               negative_flips=sum(r['negative_flip'] for r in current),forced_delta=sum(r['forced_delta'] for r in current),
                               identical_nav_paths=nav_equal,
                               cagr_positive=sum(r['CAGR_pp']>0 for r in current)))
        full=next(c for c in checks if c['group']=='full' and c['bp']==bp)
        full['track_a_pass']=full['P_pp']>=-1 and full['CAGR_pp']>=-1 and full['DD5_pp']<=3 and full['negative_flips']<=len(sw.DEFAULT_STARTS)/2
        # Standard report gets complete full/A tables; U is another paired report if distinct.
        for group in ('A', 'U') if winners['U']!=winners['A'] else ('A',):
            combined=EXP/f'sweep_full_{group}_{bp}.txt'
            combined.write_text((EXP/f'sweep_full_{bp}.txt').read_text()+'\n'.join((EXP/f'sweep_{group}_{bp}.txt').read_text().splitlines()[2:])+'\n')
            with (EXP/f'report_full_{group}_{bp}.txt').open('w') as f,contextlib.redirect_stdout(f):
                sw.report(combined, f'OI-186 成交后冷却 vs 旧计划冷却，{bp}bp（轨道A见 verification.json）')
    for name,data in (('paired_metrics.csv',pairs),('guardrails.csv',checks)):
        fields=list(dict.fromkeys(k for r in data for k in r))
        with (EXP/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(data)
    save('verification.json',dict(complete_pairing=True,zero_negative_cash=all(r['负现金日数']=='0' for r in rows),
                                 guardrails=checks,track_a_all_costs_pass=all(r['track_a_pass'] for r in checks if r['group']=='full'),
                                 current_baseline_winners_unchanged=winners['by_arm']['BASE']==winners['by_arm']['CONF'],
                                 actual_paths=complete['paths'],U_reused=winners['A']==winners['U']))
    print(json.dumps(checks,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
