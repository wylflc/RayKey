"""让网络只预测「未来三年年度 ROE 均值」，把结果当作 roe0 喂回现行 DCF。

与 nn_apply.py 的差别是**换标签不换模型**：那一版让网络直接出未来回报、再由
`V = P×((1+ĝ)/(1+r))³` 折算估值，估值被锚死在当日价格上；这一版网络只碰 ROE，
折现率、终值 ROE、增长、护栏全部沿用 `build_historical_valuation_bands.py`，
于是回测差异只能归因到 ROE 这一个输入。

**前视控制**：ROE 标签要等三个完整财年才兑现（观测日 + 约 3.5 年）。给 Y 年出预测的
模型，训练样本一律限定在观测日 < Y−4 年，且每两年才重训一次。

输出 CSV 三列 security_code,available_at,roe0，交给
`build_historical_valuation_bands.py --roe-external` 使用。
"""
import pickle, os, sys, csv, collections
import numpy as np, torch, torch.nn as nn
SC = os.path.dirname(os.path.abspath(__file__))
ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
torch.manual_seed(0); np.random.seed(0)

DATA = sys.argv[1] if len(sys.argv) > 1 else f"{SC}/nn_data.pkl"
OUT = sys.argv[2] if len(sys.argv) > 2 else f"{SC}/nn_roe_pred.csv"
CODES_FILE = sys.argv[3] if len(sys.argv) > 3 else None      # 只给这些股出预测


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


def train_one(Xtr, ytr, epochs=20, ch=12):
    net = Net(Xtr.shape[-1], ch)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
    Xt = torch.from_numpy(Xtr); yt = torch.from_numpy(ytr); bs = 1024
    for _ in range(epochs):
        net.train(); idx = torch.randperm(len(Xt))
        for i in range(0, len(idx), bs):
            b = idx[i:i + bs]; opt.zero_grad()
            nn.functional.smooth_l1_loss(net(Xt[b]), yt[b]).backward(); opt.step()
    net.eval(); return net


d = pickle.load(open(DATA, "rb"))
rows = d["rows"]
CODES = np.array([r[0] for r in rows])
DATES = np.array([r[1] for r in rows])
X = np.asarray([r[2] for r in rows], dtype=np.float32)
Y = np.array([np.nan if r[4] is None else r[4] for r in rows], dtype=np.float32)
lab = np.isfinite(Y)
print(f"样本 {len(rows):,}｜带 ROE 标签 {lab.sum():,}", flush=True)

want = None
if CODES_FILE:
    want = {ln.strip().zfill(6) for ln in open(CODES_FILE, encoding="utf-8") if ln.strip()}
    print(f"只对 {len(want)} 只出预测", flush=True)

MODELS = {}
for Yr in range(2006, 2028, 2):
    cut = f"{Yr - 4}-01-01"
    m = lab & (DATES < cut)
    if m.sum() < 3000:
        continue
    mu = X[m].reshape(-1, X.shape[-1]).mean(0); sd = X[m].reshape(-1, X.shape[-1]).std(0) + 1e-6
    net = train_one(((X[m] - mu) / sd).astype(np.float32), Y[m])
    MODELS[Yr] = (net, mu, sd)
    print(f"{Yr} 年起用的模型：训练样本 {int(m.sum()):,}（观测日 < {cut}）", flush=True)
YEARS = sorted(MODELS)

def pick(day):
    y0 = int(day[:4]); best = None
    for Yr in YEARS:
        if Yr <= y0:
            best = Yr
    return best or (YEARS[0] if YEARS else None)

sel = np.array([True] * len(rows)) if want is None else np.array([c in want for c in CODES])
sel &= DATES >= f"{YEARS[0]}-01-01"
idx = np.where(sel)[0]
print(f"待预测 {len(idx):,} 条", flush=True)

pred = {}
by_year = collections.defaultdict(list)
for i in idx:
    by_year[pick(DATES[i])].append(i)
for Yr, ids in sorted(by_year.items()):
    if Yr not in MODELS:
        continue
    net, mu, sd = MODELS[Yr]
    Z = ((X[ids] - mu) / sd).astype(np.float32)
    with torch.no_grad():
        p = net(torch.from_numpy(Z)).numpy()
    for i, v in zip(ids, p):
        pred[i] = float(v)

with open(OUT, "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh); w.writerow(["security_code", "available_at", "roe0"])
    n = 0
    for i, v in sorted(pred.items(), key=lambda t: (CODES[t[0]], DATES[t[0]])):
        v = max(0.005, min(0.45, v))          # DCF 要求 roe0 > 0；上下限与标签裁剪一致
        w.writerow([CODES[i], DATES[i], f"{v:.6f}"]); n += 1
print(f"已写 {OUT}（{n:,} 条，{len({CODES[i] for i in pred})} 只）")
