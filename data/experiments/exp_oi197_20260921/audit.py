"""Retrieve issuer implementation announcements for BASE/current decisions, with paging evidence."""
import csv,hashlib,io,json,os,re,sys,time,urllib.parse,urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from pypdf import PdfReader
EXP=Path(__file__).resolve().parent; ROOT=EXP.parents[2]
RAW=EXP/'raw_pages';RAW.mkdir(exist_ok=True)

def get(url,path):
    if path.exists(): return path.read_bytes()
    for n in range(3):
        try:
            data=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30).read()
            path.write_bytes(data);return data
        except Exception:
            if n==2:raise
            time.sleep(n+1)

def code_audit(code):
    try:
        rows=[];pages=[];total=None
        for page in range(1,100):
            params=dict(sr=-1,page_size=100,page_index=page,ann_type='A',stock_list=code,f_node=1,s_node=13,end_time='2026-09-21')
            url='https://np-anotice-stock.eastmoney.com/api/security/ann?'+urllib.parse.urlencode(params)
            data=get(url,RAW/f'notices_{code}_{page}.json');r=json.loads(data)['data']
            if total is None:total=r['total_hits']
            assert total==r['total_hits'], 'paging total changed'
            rows.extend(r['list']);pages.append(dict(url=url,sha256=hashlib.sha256(data).hexdigest()))
            if len(rows)>=total:break
            assert r['list'],'empty intermediate page'
        assert len(rows)==total
        selected=[r for r in rows if ('实施' in r['title'] and any(w in r['title'] for w in ('权益分派','分红派息','利润分配','利润分派','现金红利','分红、派息','分红及派息','转增股本')))]
        result=[]
        for r in selected:
            art=r['art_code'];url=f'https://pdf.dfcfw.com/pdf/H2_{art}_1.pdf'
            base=dict(code=code,title=r['title'],notice_date=r['notice_date'][:10],art_code=art,url=url)
            try:
                data=get(url,RAW/(art+'.pdf'));txtpath=RAW/(art+'.txt')
                if txtpath.exists():texts=json.loads(txtpath.read_text())
                else:
                    texts=[p.extract_text() or '' for p in PdfReader(io.BytesIO(data)).pages]
                    txtpath.write_text(json.dumps(texts,ensure_ascii=False))
                excerpts=[]
                for i,t in enumerate(texts):
                    t=re.sub(r'\s+','',t)
                    if any(w in t for w in ('虚拟','摊薄','差异化','回购','总股本折算')):
                        for m in re.finditer(r'虚拟|摊薄|总股本折算|除权除息参考|不参与',t):
                            excerpts.append(dict(page=i+1,text=t[max(0,m.start()-70):m.end()+230]))
                base.update(sha256=hashlib.sha256(data).hexdigest(),pages=len(texts),text_chars=sum(map(len,texts)),excerpts=excerpts)
            except Exception as e:base['error']=f'{type(e).__name__}: {e}'
            result.append(base)
        out=dict(code=code,total_announcements=total,implementation_announcements=len(selected),queries=pages,announcements=result)
    except Exception as e:out=dict(code=code,error=f'{type(e).__name__}: {e}')
    (EXP/'audit_codes').mkdir(exist_ok=True);(EXP/'audit_codes'/f'{code}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(code,len(out.get('announcements',[])),sum(bool(a.get('excerpts')) for a in out.get('announcements',[])),out.get('error',''),flush=True)
    return out

def main():
    codes=set()
    for path in ['data/processed/pit_attention/panel_moat_bank_v6b.csv','data/processed/a_share_core_valuation_pool.csv','data/processed/a_share_holdings.csv']:
        codes.update(r['security_code'] for r in csv.DictReader((ROOT/path).open()))
    codes.update(('002043','688019'))
    if len(sys.argv)>1:codes=set(sys.argv[1].split(','))
    with ThreadPoolExecutor(max_workers=min(8,int(os.getenv('SLURM_CPUS_PER_TASK','1')))) as pool:result=list(pool.map(code_audit,sorted(codes)))
    (EXP/'announcement_audit.json').write_text(json.dumps(dict(codes=sorted(codes),job_id=os.getenv('SLURM_JOB_ID'),results=result),ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
