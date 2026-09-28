import csv, glob, os
R='/gpfs/scratch1/shared/zwang/mm_quant/RayKey'
OUT='/gpfs/scratch1/nodespecific/tcn441/zwang.27284302/claude-66633/-gpfs-scratch1-shared-zwang-mm-quant-RayKey/be4702a1-b00c-45e2-9cec-3beb6af4945d/scratchpad/oi214'
codes=set(r['security_code'] for r in csv.DictReader(open(R+'/data/interim/restatement_announcements.csv',encoding='utf-8')))
rows=[]
for p in sorted(glob.glob(R+'/data/raw/financials/*.csv')):
    for r in csv.DictReader(open(p,encoding='utf-8')):
        if r['security_code'] in codes:
            r['_file']=os.path.basename(p); rows.append(r)
for p in sorted(glob.glob(R+'/data/raw/financials/superseded/*.csv')):
    for r in csv.DictReader(open(p,encoding='utf-8')):
        if r['security_code'] in codes:
            r['_file']='superseded/'+os.path.basename(p); rows.append(r)
keys=[]
for r in rows:
    for k in r:
        if k not in keys: keys.append(k)
w=csv.DictWriter(open(OUT+'/panel_cache.csv','w',encoding='utf-8',newline=''),fieldnames=keys,restval='')
w.writeheader(); w.writerows(rows)
print(len(rows))
F=['SECURITY_CODE','REPORT_DATE','NOTICE_DATE','UPDATE_DATE','TOTAL_PARENT_EQUITY','SHARE_CAPITAL','TOTAL_EQUITY','TOTAL_ASSETS','PARENT_NETPROFIT','TOTAL_OPERATE_INCOME','BASIC_EPS','NETPROFIT','NETCASH_OPERATE']
out=[]
for kind in ('balance','income','cashflow'):
    for src,path in (('cur',R+f'/data/raw/financials_statements/{kind}.csv'),('bak',R+f'/data/raw/financials_statements/{kind}.csv.bak'),('sup',R+f'/data/raw/financials_statements/superseded/{kind}.csv')):
        if not os.path.exists(path): continue
        for r in csv.DictReader(open(path,encoding='utf-8-sig')):
            c=(r.get('SECURITY_CODE') or r.get('security_code') or '').zfill(6)
            if c in codes:
                d={k:r.get(k,'') for k in F}; d['SECURITY_CODE']=c; d['kind']=kind; d['src']=src; d['superseded_at']=r.get('superseded_at','')
                d['REPORT_DATE']=d['REPORT_DATE'][:10]; d['NOTICE_DATE']=d['NOTICE_DATE'][:10]; d['UPDATE_DATE']=d['UPDATE_DATE'][:10]
                out.append(d)
w=csv.DictWriter(open(OUT+'/stmt_cache.csv','w',encoding='utf-8',newline=''),fieldnames=F+['kind','src','superseded_at'])
w.writeheader(); w.writerows(out); print(len(out))
