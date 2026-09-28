import csv, sys, time, urllib.request, os
from concurrent.futures import ThreadPoolExecutor
OUT='/gpfs/scratch1/nodespecific/tcn441/zwang.27284302/claude-66633/-gpfs-scratch1-shared-zwang-mm-quant-RayKey/be4702a1-b00c-45e2-9cec-3beb6af4945d/scratchpad/oi214'
rows=list(csv.DictReader(open('/gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/interim/restatement_announcements.csv',encoding='utf-8')))
todo=[r for r in rows if r['paired']=='0']
if len(sys.argv)>1:
    todo=[dict(url=u) for u in sys.argv[1:]]
def fetch(r):
    url=r['url']; name=url.split('/')[-2]+'_'+url.split('/')[-1]
    path=os.path.join(OUT,'pdfs',name)
    if os.path.exists(path) and os.path.getsize(path)>1000: return name,'cached',os.path.getsize(path)
    for a in range(4):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
            data=urllib.request.urlopen(req,timeout=60).read()
            open(path,'wb').write(data); return name,'ok',len(data)
        except Exception as e:
            err=str(e); time.sleep(2*(a+1))
    return name,'FAIL '+err,0
with ThreadPoolExecutor(4) as ex:
    for res in ex.map(fetch,todo): print(*res)
