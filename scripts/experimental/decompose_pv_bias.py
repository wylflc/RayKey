"""哪种分组最能解释各票 P/V 的固有偏置：护城河（质量分层）／行业／两者共同。

**这是描述性分解，不是策略**——用全样本中位数，只回答「偏置能被什么解释」。
真要拿去改中轴，必须换成逐年扩窗的时点估计（见本轮后半段）。

被解释量取 `log(长期 P/V 中位)`——取对数是因为偏置是乘性的（0.5× 与 2× 应当对称）。
解释力 R² = 1 − 组内平方和 / 总平方和。
"""
import collections
import csv
import math
import statistics

from pathlib import Path
ROOT = str(Path(__file__).resolve().parents[2])

# ---- 被解释量：长期 P/V 中位 ----
series = collections.defaultdict(list)
with open(f"{ROOT}/data/processed/a_share_daily_states_adopted.csv", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        try:
            series[r["security_code"]].append(float(r["valuation_ratio"]))
        except (TypeError, ValueError):
            pass
bias = {c: statistics.median(v) for c, v in series.items() if len(v) >= 250}

# ---- 分组器 ----
industry = {}
names = {}
with open(f"{ROOT}/data/interim/a_share_company_profiles.csv", encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        c = (r.get("security_code") or "").zfill(6)
        if r.get("eastmoney_industry"):
            industry[c] = r["eastmoney_industry"].strip()
        if r.get("security_name"):
            names[c] = r["security_name"].strip()

tier = {}
for f in ("data/processed/a_share_watchlist_quality_tiers.csv",
          "data/processed/a_share_core_valuation_pool.csv"):
    with open(f"{ROOT}/{f}", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            c = (r.get("security_code") or "").zfill(6)
            if r.get("quality_tier"):
                tier.setdefault(c, r["quality_tier"])

lvl = lambda c, n: "-".join(industry[c].split("-")[:n]) if c in industry else None
GROUPERS = {
    "行业·一级": lambda c: lvl(c, 1),
    "行业·二级": lambda c: lvl(c, 2),
    "行业·三级": lambda c: lvl(c, 3),
    "护城河（质量分层）": lambda c: tier.get(c),
    "共同（一级行业 × 分层）": lambda c: (f"{lvl(c,1)}|{tier[c]}" if c in tier and lvl(c, 1) else None),
    "共同（二级行业 × 分层）": lambda c: (f"{lvl(c,2)}|{tier[c]}" if c in tier and lvl(c, 2) else None),
}


def r2(codes, key):
    """组间解释力。**同时报组数**——组数逼近样本数时 R² 必然趋近 1，那是过拟合不是解释。"""
    vals = {c: math.log(bias[c]) for c in codes}
    groups = collections.defaultdict(list)
    for c, v in vals.items():
        groups[key(c)].append(v)
    grand = statistics.mean(vals.values())
    sst = sum((v - grand) ** 2 for v in vals.values())
    sse = sum((v - statistics.mean(g)) ** 2 for g in groups.values() for v in g)
    return (1 - sse / sst if sst else 0.0), len(groups), len(vals)


def report(title, codes):
    print(f"\n{title}（n={len(codes)}）")
    print(f"  {'分组方式':<22}{'组数':>6}{'R²':>9}{'每组均值':>10}")
    for label, key in GROUPERS.items():
        subset = [c for c in codes if key(c) is not None]
        if len(subset) < 20:
            print(f"  {label:<22}{'—':>6}{'覆盖不足':>11}")
            continue
        val, ng, n = r2(subset, key)
        print(f"  {label:<22}{ng:>6}{val:>9.3f}{n / ng:>10.1f}")


all_codes = [c for c in bias if c in industry]
both_codes = [c for c in bias if c in industry and c in tier]
report("A. 全部有行业的样本", all_codes)
report("B. 分层与行业都有的子样本（可比）", both_codes)

print("\n各一级行业的 P/V 偏置中位（全样本）：")
g = collections.defaultdict(list)
for c in all_codes:
    g[lvl(c, 1)].append(bias[c])
for k, v in sorted(g.items(), key=lambda kv: -statistics.median(kv[1])):
    if len(v) >= 3:
        print(f"  {k:<14}n={len(v):>3}  中位 {statistics.median(v):>5.2f}")

print("\n各分层的 P/V 偏置中位：")
g2 = collections.defaultdict(list)
for c in both_codes:
    g2[tier[c]].append(bias[c])
for k in sorted(g2):
    print(f"  {k}  n={len(g2[k]):>3}  中位 {statistics.median(g2[k]):>5.2f}")
