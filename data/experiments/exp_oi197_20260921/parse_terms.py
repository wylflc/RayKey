"""Conservative announcement extraction; unresolved/ambiguous rows never become overrides."""
import csv,json,re,sys
from collections import Counter,defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
EXP=Path(__file__).resolve().parent;ROOT=EXP.parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import corporate_actions as ca
NUM=r'(\d+(?:\.\d+)?)'

def extract(text,cash,ratio):
    cash_hits=[];ratio_hits=[]
    # A literal exchange-reference formula, not a discounted price or tax table.
    for m in re.finditer(r'(?:除权[（(]息[）)]|除权除息|除息).{0,12}价[格]?[^。；;]{0,450}',text):
        part=m.group()
        for p in re.finditer(r'(?:收盘价(?:格)?|前收盘价格)[）)]?[-－−–—﹣‒](?:人民币)?'+NUM+r'(?=元|[）)÷/。；]|三、|$)',part):
            cash_hits.append((Decimal(p[1]),part))
        for p in re.finditer(r'每股现金(?:红利|分红)[^（(=＝]{0,10}[（(](?:即)?'+NUM+r'元/股',part):
            cash_hits.append((Decimal(p[1]),part))
    literal_cash = list(cash_hits)
    # Virtual/smeared per-share cash equations, keeping the announced terminal value.
    for m in re.finditer(r'(?:虚拟[^。；;]{0,35}(?:现金红利|现金股利|现金分红)|(?:折算|摊薄)[^。；;]{0,20}每股(?:现金红利|现金分红)[^=＝]{0,15})[=＝][^。；;]{0,300}',text):
        part=m.group()
        hits=list(re.finditer(r'[=＝≈]'+NUM+r'(?:元(?:/股)?|[（(]保留|[（(]含税|$)',part))
        if hits:cash_hits.append((Decimal(hits[-1][1]),part))
    if literal_cash:
        cash_hits = literal_cash
    if ratio:
        for m in re.finditer(r'(?:除权[（(]息[）)]|除权除息|除息).{0,12}价[格]?[^。；;]{0,450}',text):
            part=m.group()
            for p in re.finditer(r'[÷/][（(]1[+]'+NUM+r'(%)?(?:股)?[）)]',part):
                ratio_hits.append((Decimal(p[1]) / (100 if p[2] else 1),part))
            for p in re.finditer(r'[÷/]'+NUM+r'(?:元|[。；;]|$)',part):
                if Decimal(p[1]) >= 1: ratio_hits.append((Decimal(p[1])-1,part))
        for m in re.finditer(r'(?:虚拟[^。；;]{0,25})?(?:流通股份变动比例|送转比例|转增比例)[=＝][^。；;]{0,260}',text):
            part=m.group();hits=list(re.finditer(r'[≈]'+NUM+r'(?![.\d])',part))
            if hits:ratio_hits.append((Decimal(hits[-1][1]),part))
    else:ratio_hits=[(Decimal(0),'实际无送转')]
    # Conservative ranges reject totals, historic price examples and per-10 amounts.
    cash_hits=[(v,s) for v,s in cash_hits if Decimal(0)<=v<=cash+max(Decimal('.00000051'), Decimal(5).scaleb(v.as_tuple().exponent-1))]
    if not cash:cash_hits=[(Decimal(0),'实际无现金')]
    ratio_hits=[(v,s) for v,s in ratio_hits if Decimal(0)<=v<=ratio+Decimal('.000001')]
    cs={v for v,_ in cash_hits};rs={v for v,_ in ratio_hits}
    return (next(iter(cs)) if len(cs)==1 else None,next(iter(rs)) if len(rs)==1 else None,cash_hits,ratio_hits)

def main():
    with (ROOT/'data/raw/corporate_actions/a_share_corporate_actions.csv').open() as f:events=ca.aggregate_actions(ca.correct_components(csv.DictReader(f)))
    bycode=defaultdict(list)
    for r in events:bycode[r['security_code']].append(r)
    results=[]
    for path in sorted((EXP/'audit_codes').glob('*.json')):
        for a in json.loads(path.read_text()).get('announcements',[]):
            base={k:a[k] for k in ('code','title','notice_date','art_code','url')}
            if '实施公告' not in a['title'] and '实施的公告' not in a['title']:
                results.append(dict(base,status='related_notice_not_implementation'));continue
            if 'error' in a:results.append(dict(base,status='source_unavailable',error=a['error']));continue
            pages=json.loads((EXP/'raw_pages'/f"{a['art_code']}.txt").read_text());text=re.sub(r'\s+','',''.join(pages))
            uniform = bool(re.search(r'差异化[^：:。]{0,16}[：:]否|不涉及差异化', text))
            if uniform or not re.search(r'虚拟|总股本折算|差异化(?:权益)?分[红派]|不参与.{0,30}(?:分红|分配|分派)',text):
                results.append(dict(base,status='no_differential_marker',source_sha256=a['sha256']));continue
            possible=[]
            for ev in bycode[a['code']]:
                ex=ev['ex_dividend_date'];y,m,d=map(int,ex.split('-'))
                if 0<=(date.fromisoformat(ex)-date.fromisoformat(a['notice_date'])).days<=35 and re.search(fr'{y}(?:年|/|-|\.)0?{m}(?:月|/|-|\.)0?{d}(?:日|\D|$)',text):possible.append(ev)
            if len(possible)!=1:
                results.append(dict(base,status='ambiguous_or_missing_event',event_dates=[r['ex_dividend_date'] for r in possible]));continue
            ev=possible[0];cash=Decimal(str(ev['cash_per_share']));ratio=Decimal(str(ev['share_ratio']))
            pc,ps,ch,sh=extract(text,cash,ratio)
            # The implementation's actual cash appears independently of the exchange equation.
            actual=[]
            for m in re.finditer(r'每(10|一|1)?股(?:[^，。；;]{0,20}派[^，。；;]{0,20}?|现金红利|现金股利)'+NUM+r'元',text):
                actual.append(Decimal(m[2])/(10 if m[1]=='10' else 1))
            for m in re.finditer(r'每份存托凭证现金红利[：:]?'+NUM+r'元',text):
                actual.append(Decimal(m[1]))
            for m in re.finditer(r'每股[^\d。；]{0,25}'+NUM+r'元',text):
                actual.append(Decimal(m[1]))
            actual_ok=any(abs(v-cash)<=Decimal('.00000051') for v in actual) or not cash
            status='verified_formula' if pc is not None and ps is not None and actual_ok else 'needs_review'
            source_pages=[str(i+1) for i,p in enumerate(pages) if any(re.sub(r'\s+','',p).find(s)>=0 for _,s in ch+sh if len(s)>10)]
            results.append(dict(base,status=status,event=ev,price_cash=None if pc is None else str(pc),price_ratio=None if ps is None else str(ps),
                source_sha256=a['sha256'],source_pages=';'.join(source_pages),actual_verified=actual_ok,
                actual_candidates=list(map(str,actual)),cash_evidence=[(str(v),s) for v,s in ch],share_evidence=[(str(v),s) for v,s in sh]))
    (EXP/'parsed_terms.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    print(Counter(r['status'] for r in results))
    verified=[r for r in results if r['status']=='verified_formula'];print('verified',len(verified),'different',sum(float(r['price_cash'])!=r['event']['cash_per_share'] or float(r['price_ratio'])!=r['event']['share_ratio'] for r in verified))
if __name__=='__main__':main()
