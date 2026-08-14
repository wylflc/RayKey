"""两种新校准：①方差归一（把各行业 log P/V 的离散度也拉齐）；②部分校准（因子开 α 次方）。

①`zscore`：`log P/V'' = (log P/V − μ_g) × (σ_pool / σ_g)`，即把 `P/V` 变成跨行业可比的 z 分。
  用户设想「医药方差大」——实测不成立（医药 σ=0.556 是全池 0.633 的 0.88 倍），
  但方差归一本身仍是独立于该设想的一个变换，故照测。
②`alpha`：`V' = V × f_g^α`。α=0 即基准（完全保留行业估值落差），α=1 即 §12.45 的完全校准。
  用来找「保留价值倾斜、只削弱极端处」的中间点。

两者都逐年扩窗、只用当年之前的数据，样本不足退回不校准。
"""
import bisect, collections, csv, math, statistics, sys
ROOT="/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
SRC, DST, MODE, PARAM = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
MIN_OBS, MIN_CODES, BURN = 500, 3, 5
K_CLIP = (0.5, 2.0)          # σ 比值的夹断：小样本行业的 σ 可能极小，不夹断会把带炸掉

ind={}
for r in csv.DictReader(open(f"{ROOT}/data/interim/a_share_company_profiles.csv",encoding="utf-8-sig")):
    c=(r.get("security_code") or "").zfill(6)
    if r.get("eastmoney_industry"): ind[c]=r["eastmoney_industry"].split("-")[0]

rows=list(csv.DictReader(open(SRC,newline="",encoding="utf-8")))
fields=list(rows[0].keys())
hist=collections.defaultdict(list)
for r in rows:
    g=ind.get(r["security_code"].zfill(6))
    if not g: continue
    try: pv=float(r["valuation_ratio"])
    except (TypeError,ValueError): continue
    if pv>0: hist[g].append((r["date"], math.log(pv), r["security_code"]))
for g in hist: hist[g].sort()

years=sorted({r["date"][:4] for r in rows}); start=str(int(years[0])+BURN)
par={}
for y in years:
    if y<start:
        for g in hist: par[(y,g)]=(0.0,1.0)
        continue
    wins={}
    for g,seq in hist.items():
        cut=bisect.bisect_left(seq,(f"{y}-01-01",))
        w=seq[:cut]
        wins[g]=w if len(w)>=MIN_OBS and len({c for _,_,c in w})>=MIN_CODES else None
    allv=[v for w in wins.values() if w for _,v,_ in w]
    spool=statistics.pstdev(allv) if len(allv)>2 else 1.0
    for g,w in wins.items():
        if not w: par[(y,g)]=(0.0,1.0); continue
        mu=statistics.median(v for _,v,_ in w)
        if MODE=="alpha":
            par[(y,g)]=(mu*PARAM, 1.0)
        else:
            sg=statistics.pstdev([v for _,v,_ in w]) or spool
            k=min(max(spool/sg, K_CLIP[0]), K_CLIP[1])
            par[(y,g)]=(mu, k)

out=[]; n=0
for r in rows:
    g=ind.get(r["security_code"].zfill(6))
    mu,k = par.get((r["date"][:4],g),(0.0,1.0)) if g else (0.0,1.0)
    if mu==0.0 and k==1.0: out.append(r); continue
    try:
        pv=float(r["valuation_ratio"]); close=float(r["close"])
    except (TypeError,ValueError): out.append(r); continue
    if pv<=0 or close<=0: out.append(r); continue
    lp=(math.log(pv)-mu)*k
    npv=math.exp(lp); niv=close/npv
    old=float(r["intrinsic_value"]) if r.get("intrinsic_value") else None
    r["valuation_ratio"]=f"{npv:.6f}"; r["intrinsic_value"]=f"{niv:.6f}"
    if old and old>0:
        s=niv/old
        for kk in ("band_low","band_high"):
            if r.get(kk):
                try: r[kk]=f"{float(r[kk])*s:.6f}"
                except ValueError: pass
    out.append(r); n+=1
csv.DictWriter(open(DST,"w",newline="",encoding="utf-8"),fieldnames=fields).writerows([dict(zip(fields,fields))]+out) if False else None
with open(DST,"w",newline="",encoding="utf-8") as fh:
    w=csv.DictWriter(fh,fieldnames=fields); w.writeheader(); w.writerows(out)
print(f"{MODE} param={PARAM}｜{len(hist)} 组｜{n:,}/{len(out):,} 行被变换 → {DST.split('/')[-1]}")
