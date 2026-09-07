#!/usr/bin/env python3
"""Independent local checks of the OI-150 final artifacts (no fetch or valuation)."""
import csv
import hashlib
import json
import math
import statistics
import subprocess
from datetime import datetime,timezone
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / 'data/experiments/exp_oi150_overseas_forward'
SOURCE_COMMIT = '1e348a08'
BUCKETS = ((0,.8),(.8,1.0454),(1.0454,1.2),(1.2,1.6),(1.6,2),(2,2.4257),(2.4257,4),(4,99))


def read(p):
    with Path(p).open(newline='') as f:
        return list(csv.DictReader(f))


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def rho(pairs):
    def ranks(vals):
        count=Counter(vals)
        rank={};offset=0
        for v,n in sorted(count.items()):
            rank[v]=offset+(n+1)/2;offset+=n
        return [rank[v] for v in vals]
    x=ranks([p for p,_ in pairs]);y=ranks([v for _,v in pairs])
    if len(x)<2 or len(set(x))<2 or len(set(y))<2:return None
    return statistics.correlation(x,y)


def related_study_audit():
    """Record why the existing OI-159 table cannot substitute for this study."""
    spans=defaultdict(list)
    for r in read(ROOT/'data/processed/pit_attention/panel_sp500_us.csv'):
        spans[r['security_code']].append((r['effective_from'],r['effective_to'] or '9999-12-31'))
    ends={}
    for c in spans:
        path=ROOT/f'data/raw/ohlcv_us/{c}.csv'
        if path.exists():
            per_month={}
            for r in read(path):per_month[r['date'][:7]]=r['date']
            ends[c]=set(per_month.values())
    n=bad=0;examples=[]
    path=ROOT/'data/processed/us_daily_states_adopted.csv'
    with path.open() as f:
        for r in csv.DictReader(f):
            c,t=r['security_code'],r['date']
            if t<'2012-05-01' or t not in ends.get(c,()) or not any(a<=t<=b for a,b in spans[c]):continue
            n+=1
            if r['band_available_at']>t:
                bad+=1
                if len(examples)<5:examples.append({k:r[k] for k in ('security_code','date','band_available_at','valuation_ratio')})
    clipped=[]
    for r in read(ROOT/'data/raw/ohlcv_us/price_index.csv'):
        for key in r['series'].split('|'):
            provider,symbol=key.split(':',1)
            path=ROOT/f'data/experiments/exp_us_sp500_port/raw/prices/{provider}/{symbol.replace(".","-")}.json'
            if not path.exists():continue
            payload=json.loads(path.read_text())
            if provider=='yahoo':
                result=(payload.get('chart') or {}).get('result') or []
                node=result[0] if result else {}
                quote=(node.get('indicators') or {}).get('quote') or [{}]
                closes=quote[0].get('close') or []
                stamps=[t for i,t in enumerate(node.get('timestamp',[]))
                        if i<len(closes) and closes[i] is not None and closes[i]>0]
                days=[datetime.fromtimestamp(t,tz=timezone.utc).date().isoformat() for t in stamps]
                last=max((d for d in days if d<='2026-09-04'),default='')
            else:
                last=max((str(x.get('date',''))[:10] for x in payload if x.get('close') and
                          str(x.get('date',''))[:10]<='2026-09-04'),default='') if isinstance(payload,list) else ''
            if last>r['last_date']:
                clipped.append(dict(cik=r['cik'],production_end=r['last_date'],source_end=last,source=key))
                break
    out=dict(monthly_observations=n,monthly_before_filed=bad,examples=examples,
             truncated_company_series=len(clipped),truncated_examples=clipped[:10],
             states_sha256=sha(ROOT/'data/processed/us_daily_states_adopted.csv'))
    (EXP/'related_oi159_input_audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    return out


def main():
    report=json.loads((EXP/'result.json').read_text())
    rows=read(EXP/'pv_monthly.csv')
    checks={}
    for fn in ('universe.csv','universe_ciks.csv'):
        rel=str((EXP/fn).relative_to(ROOT))
        frozen=subprocess.run(['git','show',f'{SOURCE_COMMIT}:{rel}'],cwd=ROOT,capture_output=True,check=True).stdout
        assert (EXP/fn).read_bytes()==frozen
    checks['original_universe_byte_identical']=True
    assert len(rows)==52800 and len({(r['cik'],r['date']) for r in rows})==52800
    assert len({r['cik'] for r in rows})==653
    assert all(not r['max_filed'] or r['max_filed']<=r['date'] for r in rows)
    assert all(not r['period'] or r['period']<=r['date'] for r in rows)
    checks['complete_original_observations_and_no_future_facts']=True
    for r in rows:
        if r['pv']:
            p,v,pv=float(r['price']),float(r['value']),float(r['pv'])
            assert all(math.isfinite(x) and x>0 for x in (p,v,pv))
            assert abs(p-v*pv)<=1e-6+abs(pv)*5e-9+abs(v)*5e-9
        for h in (3,5):
            if r[f'fwd{h}']:assert math.isfinite(float(r[f'fwd{h}'])) and float(r[f'fwd{h}'])>-1
    checks['valuation_arithmetic_and_finite_returns']=True
    for h in (3,5):
        used=[r for r in rows if r['pv'] and 0<=float(r['pv'])<99 and r[f'fwd{h}']]
        result=report['horizons'][str(h)]
        assert result['n']==len(used)
        pairs=[(float(r['pv']),float(r[f'fwd{h}'])) for r in used]
        assert abs(rho(pairs)-result['rho'])<1e-12
        med=[]
        for (lo,hi),b in zip(BUCKETS,result['buckets']):
            selected=[r for r in used if lo<=float(r['pv'])<hi]
            vals=[float(r[f'fwd{h}']) for r in selected]
            value=statistics.median(vals) if vals else None
            assert b['n']==len(vals) and b['companies']==len({r['cik'] for r in selected})
            assert value==b['median']
            med.append(value)
        assert abs((med[1]-med[3])*100-result['gap_pp'])<1e-12
        neg=0
        for g in result['groups']:
            group=[r for r in used if int(r['date'][:4])-(int(r['date'][5:7])<4)==g['year']]
            rr=rho([(float(r['pv']),float(r[f'fwd{h}'])) for r in group])
            assert len(group)==g['n'] and abs(rr-g['rho'])<1e-12
            neg+=rr<0
        assert neg==result['negative_groups']
    checks['independent_tied_rank_bins_and_year_groups']=True
    missing=sum(not r['price'] for r in rows)
    assert missing==report['prereg_market_missing']
    assert report['outcome']=='不可判' and report['reasons']
    checks['original_price_gate_and_final_verdict']=True
    manifest=json.loads((EXP/'manifest.json').read_text())
    for p,h in manifest['inputs'].items():assert sha(ROOT/p)==h
    for p,h in report['artifacts'].items():assert sha(EXP/p)==h
    for r in read(EXP/'price_sources.csv'):
        if r['status']=='ok':assert sha(ROOT/r['source'])==r['sha256']
    checks['all_input_source_and_output_hashes']=True
    frames=read(EXP/'universe_pit_audit.csv')
    assert len(frames)==4400 and len({(r['cy'],r['cik']) for r in frames})==4400
    assert dict(Counter(r['status'] for r in frames))==report['universe_pit']
    checks['all_original_company_years_audited']=True
    result=dict(checks=checks, all_passed=all(checks.values()),
                preregistration_sha256=sha(ROOT/'docs/reports/overseas_pv_forward_prereg.zh.md'),
                source_commit=SOURCE_COMMIT, original_companies=653, original_company_months=52800,
                result_sha256=sha(EXP/'result.json'))
    related=related_study_audit()
    result['related_study']=dict(monthly_before_filed=related['monthly_before_filed'],
                                truncated_company_series=related['truncated_company_series'])
    (EXP/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
