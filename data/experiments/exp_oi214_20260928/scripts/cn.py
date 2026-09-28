"""cn.py CODE FROM TO [title_regex]  -> list cninfo announcements for a stock in a date window"""
import json, re, sys, time, urllib.parse, urllib.request, os
UA={"User-Agent":"Mozilla/5.0","Content-Type":"application/x-www-form-urlencoded; charset=UTF-8"}
CACHE='/gpfs/scratch1/nodespecific/tcn441/zwang.27284302/claude-66633/-gpfs-scratch1-shared-zwang-mm-quant-RayKey/be4702a1-b00c-45e2-9cec-3beb6af4945d/scratchpad/oi214/orgids.json'
def post(url,params):
    for a in range(5):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url,data=urllib.parse.urlencode(params).encode(),headers=UA),timeout=40).read())
        except Exception as e:
            time.sleep(3*(a+1))
    raise RuntimeError(url)
def orgid(code):
    c=json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    if code in c: return c[code]
    hits=post("http://www.cninfo.com.cn/new/information/topSearch/query",dict(keyWord=code,maxNum=5))
    o=next((h["orgId"] for h in hits if h.get("code")==code),None)
    c[code]=o; json.dump(c,open(CACHE,'w')); return o
def query(code,lo,hi,col=None):
    o=orgid(code)
    col=col or ('sse' if code.startswith('6') else 'szse')
    out=[];page=1;pages=1
    while page<=pages:
        res=post("http://www.cninfo.com.cn/new/hisAnnouncement/query",dict(pageNum=page,pageSize=30,column=col,tabName="fulltext",plate="",stock=f"{code},{o}",searchkey="",secid="",category="",trade="",seDate=f"{lo}~{hi}",sortName="",sortType="",isHLtitle="true"))
        rows=res.get("announcements") or []
        total=int(res.get("totalAnnouncement") or 0); pages=max(-(-total//30),res.get("totalpages") or 0)
        out+=rows
        if not rows: break
        page+=1
    return out
if __name__=='__main__':
    code,lo,hi=sys.argv[1:4]; pat=re.compile(sys.argv[4]) if len(sys.argv)>4 else None
    for a in query(code,lo,hi):
        t=re.sub(r'</?em>','',a.get('announcementTitle') or '')
        if pat and not pat.search(t): continue
        print(a.get('adjunctUrl'), t, a.get('adjunctSize'))
