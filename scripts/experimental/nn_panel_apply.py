"""用户指定的口径：网络只在「值得关注列表」内训练，不看全市场。

滚动重训与 nn_apply 同规矩（给 Y 年出估值只用观测日 < Y−3 的样本），但训练集
限制在时点面板成员且样本落在该股当时在册的区间内。样本量因此从 17.8 万降到约 4 千，
每个滚动窗口只有几百到一千多条——这本身就是要报出来的结论之一。

估值定义沿用 nn_apply：V = P × ((1+ĝ)/(1+r))³，r = 10%。
"""
import pickle, os, sys, csv, bisect, collections, glob, math
import numpy as np, torch, torch.nn as nn
SC = os.path.dirname(os.path.abspath(__file__))
from pathlib import Path
ROOT = str(Path(__file__).resolve().parents[2])
torch.manual_seed(0); np.random.seed(0)
R = 0.10

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

def train_one(Xtr, ytr, epochs=30, ch=12):
    net = Net(Xtr.shape[-1], ch)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
    Xt = torch.from_numpy(Xtr); yt = torch.from_numpy(ytr); bs = 256
    for _ in range(epochs):
        net.train(); idx = torch.randperm(len(Xt))
        for i in range(0, len(idx), bs):
            b = idx[i:i + bs]; opt.zero_grad()
            nn.functional.smooth_l1_loss(net(Xt[b]), yt[b]).backward(); opt.step()
    net.eval(); return net

d = pickle.load(open(f"{SC}/nn_data.pkl", "rb"))
rows = d["rows"]
CODES = np.array([r[0] for r in rows]); DATES = np.array([r[1] for r in rows])
X = np.asarray([r[2] for r in rows], dtype=np.float32)
Y = np.array([np.nan if r[3] is None else r[3] for r in rows], dtype=np.float32)

spans = collections.defaultdict(list)
for r in csv.DictReader(open(f"{ROOT}/data/archive/pit-judgment-2026-08/universe_panel_pit_v2.csv", encoding="utf-8")):
    spans[r["security_code"]].append((r["effective_from"], r["effective_to"] or "2099-12-31"))
INP = np.array([any(a <= t <= b for a, b in spans.get(c, ())) for c, t in zip(CODES, DATES)])
lab = np.isfinite(Y)
print(f"面板内样本 {INP.sum():,}｜其中有标签 {(INP & lab).sum():,}", flush=True)

MODELS = {}
for Yr in range(2010, 2028, 2):
    cut = f"{Yr - 3}-01-01"
    m = INP & lab & (DATES < cut)
    if m.sum() < 200:
        print(f"{Yr}: 训练样本仅 {int(m.sum())}，跳过", flush=True); continue
    mu = X[m].reshape(-1, X.shape[-1]).mean(0); sd = X[m].reshape(-1, X.shape[-1]).std(0) + 1e-6
    MODELS[Yr] = (train_one(((X[m] - mu) / sd).astype(np.float32), Y[m]), mu, sd)
    print(f"{Yr} 年起用的模型：训练样本 {int(m.sum()):,}（观测日 < {cut}）", flush=True)
YEARS = sorted(MODELS)

# ---- 逐观测日出 ĝ，再按公告日阶梯持有到下一次公告 ----
sel = np.where(INP | np.array([c in spans for c in CODES]))[0]
def pick(day):
    y0 = int(day[:4]); best = None
    for Yr in YEARS:
        if Yr <= y0: best = Yr
    return best
byy = collections.defaultdict(list)
for i in sel:
    Yr = pick(DATES[i])
    if Yr: byy[Yr].append(i)
ghat = {}
for Yr, ids in sorted(byy.items()):
    net, mu, sd = MODELS[Yr]
    with torch.no_grad():
        p = net(torch.from_numpy(((X[ids] - mu) / sd).astype(np.float32))).numpy()
    for i, v in zip(ids, p):
        ghat.setdefault(CODES[i], []).append((DATES[i], float(v)))
for c in ghat: ghat[c].sort()
print(f"预测覆盖 {len(ghat)} 只、{sum(len(v) for v in ghat.values()):,} 条", flush=True)

# ---- 写成回测可读的逐日估值文件（照抄 nn_apply 的列） ----
BASE = f"{ROOT}/data/processed/a_share_historical_valuation_daily_pit116.csv"
OUT = f"{ROOT}/data/processed/vd_pit116_nnpanel.csv"
n = 0
with open(BASE, encoding="utf-8") as fi, open(OUT, "w", encoding="utf-8", newline="") as fo:
    rd = csv.DictReader(fi); w = csv.DictWriter(fo, fieldnames=rd.fieldnames); w.writeheader()
    for r in rd:
        seq = ghat.get(r["security_code"])
        if not seq: continue
        i = bisect.bisect_right(seq, (r["date"], float("inf"))) - 1
        if i < 0: continue
        g = seq[i][1]
        try: px = float(r["close"])
        except (TypeError, ValueError): continue
        v = px * ((1 + g) / (1 + R)) ** 3
        if v <= 0: continue
        r["intrinsic_value"] = f"{v:.4f}"
        r["band_low"] = f"{v*0.9:.4f}"; r["band_high"] = f"{v*1.1:.4f}"
        r["valuation_ratio"] = f"{px/v:.4f}"
        r["upside_to_low"] = f"{v*0.9/px-1:.4f}"
        w.writerow(r); n += 1
print(f"已写 {OUT}（{n:,} 行）")
