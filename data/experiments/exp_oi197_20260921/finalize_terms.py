"""Freeze unambiguous price facts and enumerate unresolved source coverage."""
import csv,json,sys
from pathlib import Path
from collections import Counter
EXP=Path(__file__).resolve().parent;ROOT=EXP.parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import corporate_actions as ca

def main():
    parsed=json.loads((EXP/'parsed_terms.json').read_text())
    for rule in json.loads((EXP/'manual_terms.json').read_text()):
        r = next(r for r in parsed if r['art_code'] == rule['art_code'])
        r.update(status='verified_formula', **{k:rule[k] for k in ('price_cash','price_ratio','source_pages')})
    fields=['security_code','ex_dividend_date',*ca.AMOUNTS,*ca.PRICE_FIELDS,'notice_date','source_url','source_pages','source_sha256','note']
    bykey={};conflicts=[]
    for r in parsed:
        if r['status']!='verified_formula':continue
        event=r['event'];key=event['security_code'],event['ex_dividend_date']
        if event['rights_ratio']:raise ValueError('Manual rights review required')
        row={k:event[k] for k in ('security_code','ex_dividend_date',*ca.AMOUNTS)}
        row.update(dict(zip(ca.PRICE_FIELDS,[r['price_cash'],r['price_ratio'],'0','0'])))
        row.update(notice_date=r['notice_date'],source_url=r['url'],source_pages=r['source_pages'],source_sha256=r['source_sha256'],
                   note='实施公告价格公式；实付金额按事件库既有精度核对；按日合计覆盖')
        if not row['source_pages']:
            # Formula crosses a PDF page: retain all formula-bearing page numbers.
            import re
            pages=json.loads((EXP/'raw_pages'/f"{r['art_code']}.txt").read_text())
            row['source_pages']=';'.join(str(i+1) for i,p in enumerate(pages) if any(w in p for w in ('除权','除息','虚拟','折算')))
        if not row['source_pages']:raise ValueError('Missing source page '+r['art_code'])
        if key in bykey and any(float(row[k])!=float(bykey[key][k]) for k in (*ca.AMOUNTS,*ca.PRICE_FIELDS)):
            conflicts.append(dict(key=key,a=bykey[key],b=row));continue
        if key not in bykey or row['notice_date']>bykey[key]['notice_date']:bykey[key]=row
    with (ROOT/'data/reference/a_share_exright_terms.csv').open() as f:
        for row in csv.DictReader(f):
            key=row['security_code'],row['ex_dividend_date']
            if key in bykey:assert all(float(row[k])==float(bykey[key][k]) for k in (*ca.AMOUNTS,*ca.PRICE_FIELDS)),key
            bykey[key]=row
    (EXP/'source_conflicts.json').write_text(json.dumps(conflicts,ensure_ascii=False,indent=2)+'\n')
    assert not conflicts, conflicts
    with (EXP/'price_terms_corrected.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(bykey[k] for k in sorted(bykey))
    ca.PRICE_TERMS_PATH=EXP/'price_terms_corrected.csv'
    with (EXP/'actions_corrected.csv').open() as f:events=ca.aggregate_actions(csv.DictReader(f))
    for r in events:ca.with_price_terms(r)
    unresolved=[r for r in parsed if r['status']=='needs_review' and (r['event']['security_code'],r['event']['ex_dividend_date']) not in bykey]
    (EXP/'unresolved_terms.json').write_text(json.dumps(unresolved,ensure_ascii=False,indent=2)+'\n')
    print('Rows',len(bykey),'codes',len({k[0] for k in bykey}),'unresolved formula events',len(unresolved))
    print(Counter(r['code'] for r in unresolved))
if __name__=='__main__':main()
