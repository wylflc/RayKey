"""修正 nn2 的两处，再回答「预测 ROE 到底比现行口径强多少」。

修正一：D2 打乱标签之前是假阳性。`fit()` 按**真实**验证 IC 挑最好的 epoch，
        于是即便训练标签被打乱，挑 epoch 这一步仍在偷看真标签。现在训练与验证
        标签一起打乱，且取最后一个 epoch，不做任何按真标签的挑选。
修正二：加「全市场·同等样本量」对照。面板内只有 3.7k 条样本，若它泛化不了，
        要先排除「只是样本太少」这一个平凡解释，才能归因到「只训练面板会记住公司」。

以及本轮真正的判据：现行 roe0（trend_aware 五年中位）对未来三年 ROE 的 IC 是多少？
神经网络要有用，必须显著高于它——否则等于用一个黑箱换一个中位数。
"""
import pickle, os, sys, math, collections, random, csv, bisect
import numpy as np, torch, torch.nn as nn
SC = os.path.dirname(os.path.abspath(__file__))
from pathlib import Path
ROOT = str(Path(__file__).resolve().parents[2])
torch.manual_seed(0); np.random.seed(0); random.seed(0)
sys.path.insert(0, SC)
from nn_diagnose import (Net, ic, ridge, X, YRET, YROE, CODES, DATES, INPANEL, FEATS)


def fit_plain(Xtr, ytr, epochs=25, ch=12):
    """不按验证集挑 epoch——训练完就用最后一个。D2 必须走这条路径。"""
    net = Net(Xtr.shape[-1], ch)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
    Xt = torch.from_numpy(Xtr); yt = torch.from_numpy(ytr); bs = 512
    for _ in range(epochs):
        net.train(); idx = torch.randperm(len(Xt))
        for i in range(0, len(idx), bs):
            b = idx[i:i + bs]; opt.zero_grad()
            nn.functional.smooth_l1_loss(net(Xt[b]), yt[b]).backward(); opt.step()
    net.eval(); return net


def split(mask, Y):
    m = mask & np.isfinite(Y)
    Xa, Ya, Ca, Da = X[m], Y[m], CODES[m], DATES[m]
    tr = Da < "2016-01-01"; te = Da >= "2019-01-01"
    mu = Xa[tr].reshape(-1, Xa.shape[-1]).mean(0); sd = Xa[tr].reshape(-1, Xa.shape[-1]).std(0) + 1e-6
    Z = ((Xa - mu) / sd).astype(np.float32)
    return Z, Ya, Ca, tr, te


def run(tag, mask, Y, sub_n=None, seed=0):
    Z, Ya, Ca, tr, te = split(mask, Y)
    if sub_n and tr.sum() > sub_n:                    # 同等样本量对照
        idx = np.where(tr)[0]; rng = np.random.RandomState(seed); rng.shuffle(idx)
        tr = np.zeros(len(Z), bool); tr[idx[:sub_n]] = True
    if tr.sum() < 300 or te.sum() < 200:
        print(f"{tag}: 样本不足"); return
    net = fit_plain(Z[tr], Ya[tr])
    with torch.no_grad():
        p_te = net(torch.from_numpy(Z[te])).numpy()
    real = ic(p_te, Ya[te])
    # D2：训练标签打乱，且不按真标签挑 epoch
    ysh = Ya[tr].copy(); np.random.RandomState(1).shuffle(ysh)
    net2 = fit_plain(Z[tr], ysh)
    with torch.no_grad():
        shuf = ic(net2(torch.from_numpy(Z[te])).numpy(), Ya[te])
    # D1：公司留出
    allc = sorted(set(Ca)); rng = random.Random(7); rng.shuffle(allc)
    hold = set(allc[:max(1, len(allc) // 5)])
    seen_tr = tr & np.array([c not in hold for c in Ca])
    ic_seen = ic_unseen = float("nan")
    if seen_tr.sum() > 300:
        net3 = fit_plain(Z[seen_tr], Ya[seen_tr])
        with torch.no_grad():
            p3 = net3(torch.from_numpy(Z[te])).numpy()
        hm = np.array([c in hold for c in Ca])[te]
        if hm.sum() > 50 and (~hm).sum() > 50:
            ic_unseen = ic(p3[hm], Ya[te][hm]); ic_seen = ic(p3[~hm], Ya[te][~hm])
    r_te = ic(ridge(Z[tr], Ya[tr], Z[te]), Ya[te])
    print(f"{tag:<26}{int(tr.sum()):>8,}{r_te:>+10.3f}{real:>+9.3f}{ic_seen:>+8.3f}{ic_unseen:>+9.3f}{shuf:>+8.3f}")


if __name__ == "__main__":
    full = np.ones(len(X), bool)
    print(f"{'组合':<26}{'训练样本':>8}{'岭回归':>10}{'CNN':>9}{'见过':>8}{'没见过':>9}{'打乱':>8}")
    n_panel_ret = int((INPANEL & np.isfinite(YRET) & (DATES < "2016-01-01")).sum())
    n_panel_roe = int((INPANEL & np.isfinite(YROE) & (DATES < "2016-01-01")).sum())
    run("全市场 × 回报", full, YRET)
    run("仅面板 × 回报", INPANEL, YRET)
    run("全市场 × 回报·同样本量", full, YRET, sub_n=n_panel_ret)
    run("全市场 × ROE", full, YROE)
    run("仅面板 × ROE", INPANEL, YROE)
    run("全市场 × ROE·同样本量", full, YROE, sub_n=n_panel_roe)

    # ---- 判据：现行 roe0 对未来三年 ROE 的解释力 ----
    print("\n现行口径对照：把 `roe0`（trend_aware 五年中位）当成对未来三年 ROE 的预测")
    band = collections.defaultdict(list)
    for r in csv.DictReader(open(f"{ROOT}/data/processed/a_share_historical_valuation_bands_pit116.csv",
                                 encoding="utf-8")):
        try:
            v = float(r["roe0"])
        except (TypeError, ValueError):
            continue
        if len(r.get("available_at") or "") == 10:
            band[r["security_code"]].append((r["available_at"], v))
    for c in band: band[c].sort()
    def roe0_at(c, d):
        s = band.get(c)
        if not s: return None
        i = bisect.bisect_right(s, (d, float("inf"))) - 1
        return s[i][1] if i >= 0 else None
    m = INPANEL & np.isfinite(YROE) & (DATES >= "2019-01-01")
    pairs = [(roe0_at(c, t), y) for c, t, y in zip(CODES[m], DATES[m], YROE[m])]
    pairs = [(a, b) for a, b in pairs if a is not None]
    if pairs:
        a = np.array([p[0] for p in pairs]); b = np.array([p[1] for p in pairs])
        print(f"  面板内测试期 {len(pairs):,} 条：现行 roe0 的 IC {ic(a, b):+.3f}"
              f"（平均绝对误差 {np.abs(a-b).mean():.3f}）")
    Z, Ya, Ca, tr, te = split(full, YROE)
    net = fit_plain(Z[tr], Ya[tr])
    with torch.no_grad():
        p = net(torch.from_numpy(Z[te])).numpy()
    inp_te = INPANEL[np.isfinite(YROE)][te]
    if inp_te.sum() > 50:
        print(f"  同一批样本上，全市场 CNN 的 IC {ic(p[inp_te], Ya[te][inp_te]):+.3f}"
              f"（平均绝对误差 {np.abs(p[inp_te]-Ya[te][inp_te]).mean():.3f}）")
