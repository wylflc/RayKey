"""四种「训练集 × 标签」组合的对照诊断。

训练集：全市场 5,111 家  vs  仅时点关注面板（116 家，且样本须落在该股当时在册的区间内）
标  签：未来三年年化总回报（估值直接由它折算）  vs  未来三年年度 ROE 均值（喂回现行 DCF）

每个组合都跑同一套防记忆诊断：
  D1 公司留出——20% 公司整体不参与训练，比较「见过 / 没见过」的 IC；
  D2 打乱标签——IC 必须塌到 0，否则说明结构本身能凭输入反推标签；
  D3 岭回归对照——打不过线性就不该上神经网络。
"""
import pickle, os, sys, math, collections, random, csv, bisect
import numpy as np, torch, torch.nn as nn
SC = os.path.dirname(os.path.abspath(__file__))
from pathlib import Path
ROOT = str(Path(__file__).resolve().parents[2])
torch.manual_seed(0); np.random.seed(0); random.seed(0)

d = pickle.load(open(f"{SC}/nn_data.pkl", "rb"))
FEATS = d["feats"]; rows = d["rows"]

# ---------- 时点面板成员：(code, obs) 必须落在该股在册区间内 ----------
def panel_spans():
    spans = collections.defaultdict(list)
    for r in csv.DictReader(open(f"{ROOT}/data/archive/pit-judgment-2026-08/universe_panel_pit_v2.csv",
                                 encoding="utf-8")):
        spans[r["security_code"]].append((r["effective_from"], r["effective_to"] or "2099-12-31"))
    for c in spans:
        spans[c].sort()
    return spans
SPANS = panel_spans()

def in_panel(code, day):
    for a, b in SPANS.get(code, ()):
        if a <= day <= b:
            return True
    return False

CODES = np.array([r[0] for r in rows])
DATES = np.array([r[1] for r in rows])
X = np.asarray([r[2] for r in rows], dtype=np.float32)
YRET = np.array([np.nan if r[3] is None else r[3] for r in rows], dtype=np.float32)
YROE = np.array([np.nan if r[4] is None else r[4] for r in rows], dtype=np.float32)
INPANEL = np.array([in_panel(c, t) for c, t in zip(CODES, DATES)])
print(f"全样本 {len(rows):,}｜面板内 {INPANEL.sum():,}（{len({c for c,m in zip(CODES,INPANEL) if m})} 家）")


class Net(nn.Module):
    def __init__(s, nf, ch=12):
        super().__init__()
        s.body = nn.Sequential(
            nn.Conv1d(nf, ch, 3, padding=1), nn.ReLU(), nn.Dropout(0.3),
            nn.Conv1d(ch, ch, 3, padding=2, dilation=2), nn.ReLU(), nn.Dropout(0.3))
        s.head = nn.Linear(ch * 2, 1)
    def forward(s, x):
        h = s.body(x.transpose(1, 2))
        return s.head(torch.cat([h.mean(-1), h.max(-1).values], -1)).squeeze(-1)


def ic(a, b):
    if len(a) < 20: return float("nan")
    ra = np.argsort(np.argsort(a)).astype(np.float64); rb = np.argsort(np.argsort(b)).astype(np.float64)
    ra -= ra.mean(); rb -= rb.mean()
    den = math.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / den) if den else float("nan")


def fit(Xtr, ytr, Xva, yva, epochs=25, ch=12, quiet=True):
    net = Net(Xtr.shape[-1], ch)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
    Xt = torch.from_numpy(Xtr); yt = torch.from_numpy(ytr); bs = 512
    Xv = torch.from_numpy(Xva)
    best = (-9, None)
    for ep in range(epochs):
        net.train(); idx = torch.randperm(len(Xt))
        for i in range(0, len(idx), bs):
            b = idx[i:i + bs]; opt.zero_grad()
            nn.functional.smooth_l1_loss(net(Xt[b]), yt[b]).backward(); opt.step()
        net.eval()
        with torch.no_grad():
            v = ic(net(Xv).numpy(), yva)
        if v > best[0]:
            best = (v, {k: t.clone() for k, t in net.state_dict().items()})
        if not quiet: print(f"    ep{ep:>2} 验证IC {v:+.3f}")
    if best[1]: net.load_state_dict(best[1])
    net.eval(); return net, best[0]


def ridge(Xtr, ytr, Xva, lam=10.0):
    A = Xtr.reshape(len(Xtr), -1); B = Xva.reshape(len(Xva), -1)
    A = np.concatenate([A, np.ones((len(A), 1), np.float32)], 1)
    B = np.concatenate([B, np.ones((len(B), 1), np.float32)], 1)
    w = np.linalg.solve(A.T @ A + lam * np.eye(A.shape[1]), A.T @ ytr)
    return B @ w


def diagnose(tag, mask, Y):
    """mask: 参与该组合的样本；Y: 标签向量（含 nan）。按时间切 训练/验证/测试。"""
    m = mask & np.isfinite(Y)
    if m.sum() < 2000:
        print(f"\n### {tag}：可用样本仅 {m.sum():,}，不足以训练"); return None
    Xa, Ya, Ca, Da = X[m], Y[m], CODES[m], DATES[m]
    tr = Da < "2016-01-01"; va = (Da >= "2016-01-01") & (Da < "2019-01-01"); te = Da >= "2019-01-01"
    print(f"\n### {tag}\n  样本 {m.sum():,}｜公司 {len(set(Ca))}｜训练 {tr.sum():,} 验证 {va.sum():,} 测试 {te.sum():,}")
    if tr.sum() < 1000 or va.sum() < 200 or te.sum() < 200:
        print("  切分后任一段过小，跳过"); return None
    mu = Xa[tr].reshape(-1, Xa.shape[-1]).mean(0); sd = Xa[tr].reshape(-1, Xa.shape[-1]).std(0) + 1e-6
    Z = ((Xa - mu) / sd).astype(np.float32)
    # D3 岭回归
    r_va = ic(ridge(Z[tr], Ya[tr], Z[va]), Ya[va]); r_te = ic(ridge(Z[tr], Ya[tr], Z[te]), Ya[te])
    # 主模型
    net, _ = fit(Z[tr], Ya[tr], Z[va], Ya[va])
    with torch.no_grad():
        p_tr = net(torch.from_numpy(Z[tr])).numpy()
        p_va = net(torch.from_numpy(Z[va])).numpy()
        p_te = net(torch.from_numpy(Z[te])).numpy()
    # D1 公司留出
    allc = sorted(set(Ca)); rng = random.Random(7); rng.shuffle(allc)
    hold = set(allc[:max(1, len(allc) // 5)])
    seen_tr = tr & np.array([c not in hold for c in Ca])
    if seen_tr.sum() > 500:
        net2, _ = fit(Z[seen_tr], Ya[seen_tr], Z[va], Ya[va])
        with torch.no_grad():
            p2 = net2(torch.from_numpy(Z[te])).numpy()
        hm = np.array([c in hold for c in Ca])[te]
        ic_unseen = ic(p2[hm], Ya[te][hm]); ic_seen = ic(p2[~hm], Ya[te][~hm])
    else:
        ic_unseen = ic_seen = float("nan")
    # D2 打乱标签
    ysh = Ya[tr].copy(); np.random.shuffle(ysh)
    net3, _ = fit(Z[tr], ysh, Z[va], Ya[va], epochs=15)
    with torch.no_grad():
        ic_shuf = ic(net3(torch.from_numpy(Z[te])).numpy(), Ya[te])
    print(f"  D3 岭回归      验证IC {r_va:+.3f}  测试IC {r_te:+.3f}")
    print(f"  主模型 1D-CNN  训练IC {ic(p_tr,Ya[tr]):+.3f}  验证IC {ic(p_va,Ya[va]):+.3f}  测试IC {ic(p_te,Ya[te]):+.3f}")
    print(f"  D1 公司留出    见过 {ic_seen:+.3f}   没见过 {ic_unseen:+.3f}")
    print(f"  D2 打乱标签    测试IC {ic_shuf:+.3f}（须≈0）")
    return dict(n=int(m.sum()), ridge_te=r_te, cnn_te=ic(p_te, Ya[te]),
                seen=ic_seen, unseen=ic_unseen, shuf=ic_shuf)


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    full = np.ones(len(X), bool)
    jobs = [("全市场 × 回报标签", full, YRET), ("仅面板 × 回报标签", INPANEL, YRET),
            ("全市场 × ROE标签", full, YROE), ("仅面板 × ROE标签", INPANEL, YROE)]
    res = {}
    for tag, m, Y in jobs:
        if which != "all" and which not in tag: continue
        res[tag] = diagnose(tag, m, Y)
    print("\n" + "=" * 78)
    print(f"{'组合':<20}{'样本':>9}{'岭回归测试':>11}{'CNN测试':>9}{'见过':>8}{'没见过':>8}{'打乱':>8}")
    for k, v in res.items():
        if not v: continue
        print(f"{k:<20}{v['n']:>9,}{v['ridge_te']:>+11.3f}{v['cnn_te']:>+9.3f}"
              f"{v['seen']:>+8.3f}{v['unseen']:>+8.3f}{v['shuf']:>+8.3f}")


if __name__ == "__main__":
    main()
