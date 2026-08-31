"""滚动重训 + 逐日推断 → 写成回测可读的逐日估值文件。

**前视控制**：要给 Y 年出估值，只能用「标签已经兑现」的样本训练，即观测日 < Y−3年
（标签是观测日之后 3 年的回报）。每 2 年重训一次，模型只作用于其训练截止之后的年份。
故 2010 年用的模型只见过 2007 年前的观测，绝不含当年及之后的信息。

**估值定义**：网络出未来 3 年年化总回报 ĝ；要求回报 r=10%。
    V = P × ((1+ĝ)/(1+r))³      P/V = ((1+r)/(1+ĝ))³
即「按网络预期的回报折现回来，价格应该是多少」。ĝ>r 即便宜。
"""
import pickle, os, sys, math, bisect, csv, collections, random
import numpy as np, torch, torch.nn as nn
SC=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,SC)
torch.manual_seed(0); np.random.seed(0); random.seed(0)
import nn_dataset as D

class Net(nn.Module):
    def __init__(s, nf, ch=12):
        super().__init__()
        s.body=nn.Sequential(
            nn.Conv1d(nf, ch, 3, padding=1), nn.ReLU(), nn.Dropout(0.3),
            nn.Conv1d(ch, ch, 3, padding=2, dilation=2), nn.ReLU(), nn.Dropout(0.3))
        s.head=nn.Linear(ch*2, 1)
    def forward(s, x):
        h=s.body(x.transpose(1,2))
        return s.head(torch.cat([h.mean(-1), h.max(-1).values], -1)).squeeze(-1)

def train_one(Xtr,ytr,epochs=18,ch=12):
    net=Net(Xtr.shape[-1],ch)
    opt=torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
    Xt=torch.from_numpy(Xtr); yt=torch.from_numpy(ytr); bs=1024
    for ep in range(epochs):
        net.train(); idx=torch.randperm(len(Xt))
        for i in range(0,len(idx),bs):
            b=idx[i:i+bs]; opt.zero_grad()
            nn.functional.smooth_l1_loss(net(Xt[b]), yt[b]).backward(); opt.step()
    net.eval(); return net

d=pickle.load(open(f"{SC}/nn_data.pkl","rb"))
FEATS=d["feats"]; rows=d["rows"]
dates=np.array([r[1] for r in rows])
X=np.asarray([r[2] for r in rows], dtype=np.float32)
y=np.asarray([r[3] for r in rows], dtype=np.float32)
print(f"训练池 {X.shape}", flush=True)

# ---- 滚动模型：{适用起始年: (net, mu, sd)}
MODELS={}
for Y in range(2010, 2027, 2):
    cut=f"{Y-3}-01-01"
    m=dates<cut
    if m.sum()<3000: print(f"{Y}: 样本仅 {m.sum()}，跳过", flush=True); continue
    mu=X[m].reshape(-1,X.shape[-1]).mean(0); sd=X[m].reshape(-1,X.shape[-1]).std(0)+1e-6
    net=train_one(((X[m]-mu)/sd).astype(np.float32), y[m])
    MODELS[Y]=(net,mu,sd)
    print(f"{Y} 年起用的模型：训练样本 {m.sum():,}（观测日 < {cut}）", flush=True)
YEARS=sorted(MODELS)
def pick(day):
    y0=int(day[:4]); best=None
    for Y in YEARS:
        if Y<=y0: best=Y
    return MODELS.get(best) if best else None

# ---- 逐日推断
codes=[l.strip() for l in open(f"{SC}/pit116_codes.txt")]
FIN=D.load_fin()
R=0.10; H=3.0
out=open(os.path.join(os.path.dirname(os.path.dirname(SC)), "data/processed/vd_pit116_nn.csv"),"w",newline="",encoding="utf-8")
w=csv.writer(out)
w.writerow(["security_code","date","close","band_report_date","band_available_at","split_factor",
            "intrinsic_value","band_low","band_high","valuation_ratio","upside_to_low","valuation_label"])
nrow=0
for ci,code in enumerate(codes):
    recs=FIN.get(code) or []
    px=D.load_px(code)
    if px is None or len(recs)<20: print(f"  {code} 数据不足，跳过", flush=True); continue
    ds, raw, adj = px
    # 季度特征（与训练同一套代码路径）
    qf=[]
    for i,(nd, rp, r) in enumerate(recs):
        rev=D.num(r.get("total_operate_income")); np_=D.num(r.get("parent_netprofit"))
        bps=D.num(r.get("bps")); eps=D.num(r.get("deduct_basic_eps")) or D.num(r.get("basic_eps"))
        roe=D.num(r.get("weightavg_roe")); gm=D.num(r.get("gross_margin")); ocfps=D.num(r.get("op_cashflow_ps"))
        prev=D.num(recs[i-4][2].get("bps")) if i>=4 else None
        f={"roe": roe/100.0 if roe is not None else None,
           "gross_margin": gm/100.0 if gm is not None else None,
           "net_margin": (np_/rev) if (rev and np_ is not None and rev>0) else None,
           "ocf_to_np": (ocfps/eps) if (ocfps is not None and eps and abs(eps)>1e-6) else None,
           "rev_yoy": (D.num(r.get("revenue_yoy")) or 0)/100.0 if r.get("revenue_yoy") else None,
           "np_yoy": (D.num(r.get("netprofit_yoy")) or 0)/100.0 if r.get("netprofit_yoy") else None,
           "rev_qoq": (D.num(r.get("revenue_qoq")) or 0)/100.0 if r.get("revenue_qoq") else None,
           "np_qoq": (D.num(r.get("netprofit_qoq")) or 0)/100.0 if r.get("netprofit_qoq") else None,
           "bps_growth": (bps/prev-1) if (bps and prev and prev>0) else None,
           "eps_to_bps": (eps/bps) if (eps is not None and bps and bps>0) else None}
        qf.append((nd, f, bps, eps))
    nds=[t[0] for t in qf]
    batch=[]; meta=[]
    for pi,day in enumerate(ds):
        if day<"2009-01-01": continue
        j=bisect.bisect_right(nds, day)-1          # 只用已公告的
        if j<19: continue
        p=raw[pi]
        if p<=0: continue
        bps_now, eps_now = qf[j][2], qf[j][3]
        div12=sum(c for dd,(c,_r) in D.ACT.get(code,{}).items()
                  if dd<=day and dd> f"{int(day[:4])-1}{day[4:]}")
        i1=max(0,pi-244); i3=max(0,pi-61)
        m1=adj[pi]/adj[i1]-1 if adj[i1]>0 else 0.0
        m3=adj[pi]/adj[i3]-1 if adj[i3]>0 else 0.0
        seq=[]
        for q in range(j-19, j+1):
            f=dict(qf[q][1])
            f["pb"]= (p/bps_now) if bps_now and bps_now>0 else None
            f["pe_inv"]= (eps_now/p) if eps_now is not None else None
            f["div_yield"]= div12/p
            f["payout"]= (div12/eps_now) if eps_now and eps_now>1e-6 else 0.0
            f["px_mom_1y"]=m1; f["px_mom_3m"]=m3
            vec=[]
            for name in FEATS:
                v=f.get(name)
                if v is None: v=0.0
                lo,hi=D.CLIP[name]; vec.append(max(lo,min(hi,v)))
            seq.append(vec)
        batch.append(seq); meta.append((day, p, qf[j][0]))
    if not batch: continue
    A=np.asarray(batch, dtype=np.float32)
    preds=np.empty(len(A), dtype=np.float32)
    for Yi,Y in enumerate(YEARS):
        nxt=YEARS[Yi+1] if Yi+1<len(YEARS) else "9999"
        sel=[k for k,(day,_,_) in enumerate(meta) if str(Y)<=day[:4]<str(nxt)]
        if not sel: continue
        net,mu,sd=MODELS[Y]
        with torch.no_grad():
            preds[sel]=net(torch.from_numpy(((A[sel]-mu)/sd).astype(np.float32))).numpy()
    for k,(day,p,rp) in enumerate(meta):
        g=float(np.clip(preds[k], -0.35, 0.60))
        V=p*((1+g)/(1+R))**H
        if V<=0: continue
        w.writerow([code, day, f"{p:.4f}", rp, rp, "1", f"{V:.4f}",
                    f"{V*0.9:.4f}", f"{V*1.1:.4f}", f"{p/V:.6f}", f"{V*0.9/p-1:.6f}", "nn"])
        nrow+=1
    if ci%20==0: print(f"  {ci}/{len(codes)}  已写 {nrow:,}", flush=True)
out.close(); print(f"完成，{nrow:,} 行 → data/processed/vd_pit116_nn.csv")

