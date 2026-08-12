"""为估值神经网络装配训练样本。三条硬约束，每条都对应用户点名的一个失败模式：

1. **无前视**：一条样本的特征只用 `notice_date <= 观测日` 的财报，标签只用观测日**之后**的行情。
   财务字段用公告日而非报告期入账——报告期 2024-12-31 的年报要到 2025-04 才可得。
2. **无身份**：特征里没有代码、名称、行业、市值绝对值。全部是比率与增速，**跨公司同尺度**。
   网络若想「记住某家公司」，输入里没有可供记忆的钥匙。
3. **训练集≠回测池**：在全市场 12,108 家上训练，不是在 116 家时点面板上训练。
   面板只在回测时用，避免网络对着最终入选名单学。
"""
import csv, glob, collections, math, bisect, sys, os, json
ROOT="/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
OUT=os.path.dirname(os.path.abspath(__file__))

def num(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None

# ---------- 财务：按公告日排序的季度序列 ----------
def load_fin():
    per=collections.defaultdict(list)
    for f in sorted(glob.glob(f"{ROOT}/data/raw/financials/*.csv")):
        with open(f, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                nd = r.get("notice_date") or ""
                if not nd or len(nd) != 10:
                    continue                      # 无公告日 → 无法定时点，丢弃而非猜
                per[r["security_code"]].append((nd, r["report_date"], r))
    for c in per:
        per[c].sort(key=lambda t: (t[0], t[1]))
    return per

# ---------- 行情：后复权序列 ----------
def load_actions():
    out=collections.defaultdict(dict)
    for f in glob.glob(f"{ROOT}/data/raw/corporate_actions/*.csv"):
        with open(f, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                d=r.get("ex_date") or r.get("date")
                if not d: continue
                cash=num(r.get("cash_per_share")) or 0.0
                ratio=num(r.get("share_ratio")) or 0.0
                oc,orr=out[r["security_code"]].get(d,(0.0,0.0))
                out[r["security_code"]][d]=(oc+cash,(1+orr)*(1+ratio)-1)
    return out
ACT=load_actions()

def load_px(code):
    f=f"{ROOT}/data/raw/ohlcv/{code}.csv"
    if not os.path.exists(f): return None
    rows=[]
    with open(f, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            c=num(r.get("close"))
            if c and c>0: rows.append((r["date"], c))
    if len(rows)<250: return None
    rows.sort()
    ds=[d for d,_ in rows]; raw=[c for _,c in rows]
    adj=[]; factor=1.0; acc=0.0; acts=ACT.get(code,{})
    for d,c in rows:
        ev=acts.get(d)
        if ev:
            cps,ratio=ev
            factor*=(1+ratio); acc=acc*(1+ratio)+cps
        adj.append(c*factor+acc)
    return ds, raw, adj

# ---------- 特征 ----------
# 全部为比率/增速，且逐条 clip 到合理区间——极端值（分母塌陷造成的 ROE 1000%）
# 会主导 MSE，把网络训成异常值探测器。
FEATS=["roe","gross_margin","net_margin","ocf_to_np","rev_yoy","np_yoy","rev_qoq","np_qoq",
       "bps_growth","eps_to_bps","pb","pe_inv","div_yield","payout","px_mom_1y","px_mom_3m"]
CLIP={"roe":(-0.5,0.6),"gross_margin":(-0.2,1.0),"net_margin":(-0.5,0.8),"ocf_to_np":(-3,5),
      "rev_yoy":(-0.8,3),"np_yoy":(-3,5),"rev_qoq":(-0.8,3),"np_qoq":(-3,5),
      "bps_growth":(-0.5,1.5),"eps_to_bps":(-0.5,0.6),"pb":(0,20),"pe_inv":(-0.2,0.3),
      "div_yield":(0,0.15),"payout":(0,2),"px_mom_1y":(-0.8,3),"px_mom_3m":(-0.6,1.5)}

def build(seq_len=20, horizon_days=756, min_hist=12):
    """seq_len 个季度的特征序列 → 未来 horizon_days 的年化总回报。"""
    FIN=load_fin(); print(f"财务：{len(FIN):,} 家", flush=True)
    rows=[]; skipped=collections.Counter()
    for k,(code, recs) in enumerate(sorted(FIN.items())):
        if k%1500==0: print(f"  ...{k}/{len(FIN)} 已产出 {len(rows):,}", flush=True)
        if len(recs)<min_hist: skipped["财报太少"]+=1; continue
        px=load_px(code)
        if px is None: skipped["无行情"]+=1; continue
        ds, raw, adj = px
        # 每份财报公告日 → 一条候选样本
        per_feats=[]
        for i,(nd, rp, r) in enumerate(recs):
            rev=num(r.get("total_operate_income")); np_=num(r.get("parent_netprofit"))
            bps=num(r.get("bps")); eps=num(r.get("deduct_basic_eps")) or num(r.get("basic_eps"))
            roe=num(r.get("weightavg_roe")); gm=num(r.get("gross_margin"))
            ocfps=num(r.get("op_cashflow_ps"))
            prev_bps = num(recs[i-4][2].get("bps")) if i>=4 else None
            f={}
            f["roe"]= roe/100.0 if roe is not None else None
            f["gross_margin"]= gm/100.0 if gm is not None else None
            f["net_margin"]= (np_/rev) if (rev and np_ is not None and rev>0) else None
            f["ocf_to_np"]= (ocfps/eps) if (ocfps is not None and eps and abs(eps)>1e-6) else None
            f["rev_yoy"]= (num(r.get("revenue_yoy")) or 0)/100.0 if r.get("revenue_yoy") else None
            f["np_yoy"]= (num(r.get("netprofit_yoy")) or 0)/100.0 if r.get("netprofit_yoy") else None
            f["rev_qoq"]= (num(r.get("revenue_qoq")) or 0)/100.0 if r.get("revenue_qoq") else None
            f["np_qoq"]= (num(r.get("netprofit_qoq")) or 0)/100.0 if r.get("netprofit_qoq") else None
            f["bps_growth"]= (bps/prev_bps-1) if (bps and prev_bps and prev_bps>0) else None
            f["eps_to_bps"]= (eps/bps) if (eps is not None and bps and bps>0) else None
            per_feats.append((nd, rp, f, bps, eps))
        # 逐条样本：用第 j 条公告日作为观测日
        for j in range(seq_len-1, len(per_feats)):
            obs = per_feats[j][0]
            pi = bisect.bisect_left(ds, obs)
            if pi>=len(ds): continue
            p_raw, p_adj = raw[pi], adj[pi]
            # 估值与股息：只用观测日当天的价 + 已公告的每股数
            bps_now, eps_now = per_feats[j][3], per_feats[j][4]
            div12 = sum(c for d,(c,_r) in ACT.get(code,{}).items()
                        if d<=obs and d> f"{int(obs[:4])-1}{obs[4:]}")
            # 一年/三月动量（后复权），只回看
            def mom(days):
                t=ds[max(0, bisect.bisect_left(ds, obs)-days)]
                i0=bisect.bisect_left(ds,t)
                return adj[pi]/adj[i0]-1 if adj[i0]>0 else None
            seq=[]
            ok=True
            for q in range(j-seq_len+1, j+1):
                f=dict(per_feats[q][2])
                f["pb"]= (p_raw/bps_now) if bps_now and bps_now>0 else None
                f["pe_inv"]= (eps_now/p_raw) if eps_now is not None and p_raw>0 else None
                f["div_yield"]= div12/p_raw if p_raw>0 else 0.0
                f["payout"]= (div12/eps_now) if eps_now and eps_now>1e-6 else 0.0
                f["px_mom_1y"]= mom(244); f["px_mom_3m"]= mom(61)
                vec=[]
                miss=0
                for name in FEATS:
                    v=f.get(name)
                    if v is None: v=0.0; miss+=1
                    lo,hi=CLIP[name]; v=max(lo,min(hi,v))
                    vec.append(v)
                if miss>len(FEATS)*0.5: ok=False; break
                seq.append(vec)
            if not ok or len(seq)!=seq_len: continue
            # 标签：观测日之后 horizon_days 的年化后复权总回报
            fi=bisect.bisect_left(ds, obs)
            ti=fi+int(horizon_days/365*244)
            if ti>=len(ds): continue
            if adj[fi]<=0: continue
            tot=adj[ti]/adj[fi]
            if tot<=0: continue
            yrs=horizon_days/365.0
            y=tot**(1/yrs)-1
            y=max(-0.6, min(1.5, y))
            rows.append((code, obs, seq, y))
    print(f"样本 {len(rows):,}  跳过 {dict(skipped)}", flush=True)
    return rows

if __name__=="__main__":
    import pickle
    rows=build()
    with open(f"{OUT}/nn_data.pkl","wb") as fh: pickle.dump({"feats":FEATS,"rows":rows}, fh)
    print("已写", f"{OUT}/nn_data.pkl")
