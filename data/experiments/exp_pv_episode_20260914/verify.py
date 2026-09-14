"""Independent artifact, interval and cash-return checks for this fixed audit."""
import csv,hashlib,json,random,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts/experimental'))
from pv_episode_forward import bhv,bt,sha
from whipsaw_swap_diag import holding_return_path
P=Path(__file__).resolve().parent

def load(name):return list(csv.DictReader((P/name).open()))

def check_hashes(name):
 d=json.loads((P/name).read_text())
 for path,h in d['input_sha256'].items():
  p=Path(path);p=p if p.is_absolute() else ROOT/p
  assert sha(p)==h,(name,path)
 for path,h in d['output_sha256'].items():assert sha(P/path)==h,(name,path)
 return d

m=check_hashes('manifest.json');r=check_hashes('rank1_manifest.json')
assert all(r['original_table_reproduced'].values()) and not r['trend_mismatches']
eps=load('episodes.csv');rank=load('rank1_observations.csv');cov=load('coverage.csv')
assert sum(int(x['missing_state_quotes']) for x in cov)==0
for source in (eps,rank):
 groups=defaultdict(list)
 for x in source:
  if 'nonoverlap' in x['group'] and x['complete']=='True':
   groups[x['group'],x['code'],x.get('horizon','250')].append(x)
 for key,rows in groups.items():
  rows.sort(key=lambda x:x['signal_date'])
  for a,b in zip(rows,rows[1:]):assert b.get('exec_date',b.get('execution_date'))>=a['end_date'],key
# All quoted samples survive to their fixed endpoint in the statistic even if the
# counting episode has already ended. In particular, failures were not dropped.
ma=[x for x in rank if x['group']=='rank1_ma60_episode' and x['horizon']=='250' and x['complete']=='True']
before=sum(bool(x['break_date']) and x['break_date']<x['end_date'] for x in ma)
assert before>0
# Existing cash-ledger calculator is independent of the new cumulative indices.
candidates=[x for x in eps if x['group']=='trend_ma60_episode' and x['complete']=='True']
random.Random(20260914).shuffle(candidates)
actions=bt.load_actions();max_cash_error=0.0
for x in candidates[:80]:
 raw=bhv.load_ohlcv(x['code']);prices=dict(raw)
 days=[d for d,p in raw if x['execution_date']<=d<=x['end_date']]
 actual=holding_return_path(prices,actions.get(x['code'],{}),days)[-1]
 error=abs(actual-float(x['cash_return_250d']));max_cash_error=max(max_cash_error,error)
 assert error<1e-10,(x,error)
# Reproduce all group summaries from their saved raw observations where available.
for filename,source,horizon_field in [('rank1_summary.csv',rank,True)]:
 import statistics
 for x in load(filename):
  rows=[z for z in source if z['group']==x['group'] and z['horizon']==x['horizon']]
  vals=[float(z['return']) for z in rows if z['complete']=='True']
  assert len(rows)==int(x['signals']) and len(vals)==int(x['complete'])
  assert abs(statistics.median(vals)-float(x['median']))<1e-12
out={'input_and_output_hashes_valid':True,'old_table_exact_n_and_rounded_median_reproduced':True,
     'rank1_strict_trend_mismatches':0,'nonoverlap_intervals_valid':True,
     'fixed_forward_includes_broken_episodes':before,'fixed_forward_total':len(ma),
     'independent_cash_ledger_checks':80,'max_cash_return_error':max_cash_error,
     'all_rank1_summary_counts_and_medians_recomputed':True,
     'source_price_end_counts':{d:sum(x['last_quote']==d for x in cov) for d in sorted(set(x['last_quote'] for x in cov))},
     'jobs':{'panel':{'job_id':26668227,'state':'COMPLETED','elapsed':'00:01:06','allocated_cpus':16,'sacct_maxrss_kb':46890},
             'rank1':{'job_id':26669176,'state':'COMPLETED','elapsed':'00:00:22','allocated_cpus':16,'sacct_maxrss_kb':1766}},
     'resource_note':'短作业的sacct采样可能低估峰值；采样值不是持续内存测量。'}
(P/'verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(out,ensure_ascii=False,indent=2))
