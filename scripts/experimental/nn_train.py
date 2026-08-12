"""估值网络的训练与三项防记忆诊断。

模型刻意做小（<6k 参数）：样本 17.8 万条但**高度相关**——同一家公司相邻季度的 20 季窗口
重叠 19 季，有效独立样本远少于名义数。大模型必然记住公司而不是学会规律。

三项诊断（对应用户「不能只是记住每家公司的财务数据」的要求）：
  D1 公司留出：20% 的公司整体不参与训练。若「见过的公司」与「没见过的公司」上的
     秩相关(IC) 接近，说明学到的是跨公司的规律而非某家公司的身份。
  D2 打乱标签：把 y 随机打乱重训，IC 必须塌到 0 附近。否则说明结构本身能凭输入
     反推标签（数据泄漏）。
  D3 线性对照：同特征的岭回归。神经网络若打不过它，就不该用神经网络。
"""
import pickle, sys, os, math, collections, random
import numpy as np, torch, torch.nn as nn
SC=os.path.dirname(os.path.abspath(__file__))
torch.manual_seed(0); np.random.seed(0); random.seed(0)

d=pickle.load(open(f"{SC}/nn_data.pkl","rb"))
FEATS=d["feats"]; rows=d["rows"]
codes=np.array([r[0] for r in rows]); dates=np.array([r[1] for r in rows])
X=np.asarray([r[2] for r in rows], dtype=np.float32)      # (N, 20, 16)
y=np.asarray([r[3] for r in rows], dtype=np.float32)
print(f"样本 {X.shape}  标签 均值 {y.mean():.3f} 标准差 {y.std():.3f}")

class Net(nn.Module):
    """时序方向用 1D-CNN（膨胀卷积覆盖 20 季），特征方向用 1x1 压缩。"""
    def __init__(s, nf, ch=12):
        super().__init__()
        s.body=nn.Sequential(
            nn.Conv1d(nf, ch, 3, padding=1), nn.ReLU(), nn.Dropout(0.3),
            nn.Conv1d(ch, ch, 3, padding=2, dilation=2), nn.ReLU(), nn.Dropout(0.3),
        )
        s.head=nn.Linear(ch*2, 1)
    def forward(s, x):                      # x: (B, T, F)
        h=s.body(x.transpose(1,2))          # (B, ch, T)
        h=torch.cat([h.mean(-1), h.max(-1).values], -1)
        return s.head(h).squeeze(-1)

def ic(a,b):
    if len(a)<20: return float("nan")
    ra=np.argsort(np.argsort(a)).astype(np.float64); rb=np.argsort(np.argsort(b)).astype(np.float64)
    ra-=ra.mean(); rb-=rb.mean()
    den=math.sqrt((ra**2).sum()*(rb**2).sum())
    return float((ra*rb).sum()/den) if den else float("nan")

def standardize(tr, *others):
    mu=tr.reshape(-1,tr.shape[-1]).mean(0); sd=tr.reshape(-1,tr.shape[-1]).std(0)+1e-6
    return [( (a-mu)/sd ).astype(np.float32) for a in (tr,)+others], (mu,sd)

def train(Xtr,ytr,Xva,yva, epochs=25, ch=12, quiet=False):
    net=Net(Xtr.shape[-1], ch)
    n=sum(p.numel() for p in net.parameters())
    opt=torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
    Xt=torch.from_numpy(Xtr); yt=torch.from_numpy(ytr)
    Xv=torch.from_numpy(Xva); best=(1e9,None)
    bs=1024
    for ep in range(epochs):
        net.train(); idx=torch.randperm(len(Xt))
        for i in range(0,len(idx),bs):
            b=idx[i:i+bs]; opt.zero_grad()
            loss=nn.functional.smooth_l1_loss(net(Xt[b]), yt[b]); loss.backward(); opt.step()
        net.eval()
        with torch.no_grad(): pv=net(Xv).numpy()
        mse=float(((pv-yva)**2).mean())
        if mse<best[0]: best=(mse, {k:v.clone() for k,v in net.state_dict().items()})
    net.load_state_dict(best[1]); net.eval()
    if not quiet: print(f"    参数 {n}  最优验证MSE {best[0]:.4f}")
    return net

def ridge(Xtr,ytr,lam=10.0):
    A=Xtr.reshape(len(Xtr),-1); A=np.c_[A, np.ones(len(A))]
    w=np.linalg.solve(A.T@A+lam*np.eye(A.shape[1]), A.T@ytr)
    return lambda Z: (np.c_[Z.reshape(len(Z),-1), np.ones(len(Z))]@w).astype(np.float32)

# ---------------- 时间切分：训练标签必须在验证期开始前已实现（+3年） ----------------
CUT_TR, CUT_VA = "2013-01-01", "2016-01-01"
tr = dates < CUT_TR           # 标签窗口最晚到 2016-01，恰好不越过验证期起点
va = (dates>=CUT_VA) & (dates<"2019-01-01")
te = dates>="2022-01-01"
print(f"训练 {tr.sum():,}  验证 {va.sum():,}  测试 {te.sum():,}")
(Xtr,Xva,Xte),_=standardize(X[tr],X[va],X[te])
ytr,yva,yte=y[tr],y[va],y[te]

print("\n[D3] 线性对照（岭回归）")
f=ridge(Xtr,ytr); print(f"    训练IC {ic(f(Xtr),ytr):+.3f}   验证IC {ic(f(Xva),yva):+.3f}   测试IC {ic(f(Xte),yte):+.3f}")

print("[主模型] 1D-CNN")
net=train(Xtr,ytr,Xva,yva)
with torch.no_grad():
    ptr=net(torch.from_numpy(Xtr)).numpy(); pva=net(torch.from_numpy(Xva)).numpy(); pte=net(torch.from_numpy(Xte)).numpy()
print(f"    训练IC {ic(ptr,ytr):+.3f}   验证IC {ic(pva,yva):+.3f}   测试IC {ic(pte,yte):+.3f}")

print("\n[D1] 公司留出：20% 公司完全不参与训练")
uc=sorted(set(codes[tr])); random.shuffle(uc); hold=set(uc[:len(uc)//5])
trh = tr & ~np.isin(codes, list(hold))
(Xtrh,), _ = standardize(X[trh])
mu=X[trh].reshape(-1,X.shape[-1]).mean(0); sd=X[trh].reshape(-1,X.shape[-1]).std(0)+1e-6
norm=lambda a: ((a-mu)/sd).astype(np.float32)
neth=train(norm(X[trh]), y[trh], norm(X[va]), y[va], quiet=True)
seen = va & ~np.isin(codes, list(hold)); unseen = va & np.isin(codes, list(hold))
with torch.no_grad():
    ps=neth(torch.from_numpy(norm(X[seen]))).numpy(); pu=neth(torch.from_numpy(norm(X[unseen]))).numpy()
print(f"    验证期·训练中见过的公司 IC {ic(ps,y[seen]):+.3f}（{seen.sum():,} 条）")
print(f"    验证期·完全没见过的公司 IC {ic(pu,y[unseen]):+.3f}（{unseen.sum():,} 条）")

print("\n[D2] 打乱标签对照")
ysh=ytr.copy(); np.random.shuffle(ysh)
nets=train(Xtr,ysh,Xva,yva,epochs=12,quiet=True)
with torch.no_grad(): pv=nets(torch.from_numpy(Xva)).numpy()
print(f"    验证IC {ic(pv,yva):+.3f}（应≈0）")

torch.save({"state":net.state_dict(),"feats":FEATS,"nf":X.shape[-1],
            "mu":X[tr].reshape(-1,X.shape[-1]).mean(0),"sd":X[tr].reshape(-1,X.shape[-1]).std(0)+1e-6},
           f"{SC}/nn_model.pt")
print("\n已存 nn_model.pt")
