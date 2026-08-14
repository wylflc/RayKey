"""按分组给估值中轴做**时点扩窗校准**，产出新的逐日状态文件。

思路：§12.44 证明每只票的 `P/V` 有固定偏置。若该偏置能被「组」解释，
就按组估一个乘数 `f_g`，把中轴改成 `V' = V × f_g`，于是 `P/V' = P/V / f_g`，组内中位归 1。

**必须时点估计，否则整轮作废。** 第 Y 年用的 `f_g` 只能由 **Y 年 1 月 1 日之前**的观测算出；
样本不足（观测 < MIN_OBS 或成员 < MIN_CODES）一律退回 1.0（即不校准），**不外推、不借用别组**。
预热期内所有 `f_g = 1`，故前几年的行为与基准逐位相同。

用法：
    python3 calib.py <输入逐日> <输出逐日> <分组:ind1|ind2|tier|ind1xtier>
"""
import bisect
import collections
import csv
import statistics
import sys

ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
SRC, DST, MODE = sys.argv[1], sys.argv[2], sys.argv[3]
MIN_OBS, MIN_CODES, BURN_IN_YEARS = 500, 3, 5

# ---- 分组器 ----
industry, tier = {}, {}
with open(f"{ROOT}/data/interim/a_share_company_profiles.csv", encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        c = (r.get("security_code") or "").zfill(6)
        if r.get("eastmoney_industry"):
            industry[c] = r["eastmoney_industry"].strip()
for f in ("data/processed/a_share_watchlist_quality_tiers.csv",
          "data/processed/a_share_core_valuation_pool.csv"):
    with open(f"{ROOT}/{f}", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            c = (r.get("security_code") or "").zfill(6)
            if r.get("quality_tier"):
                tier.setdefault(c, r["quality_tier"])

lvl = lambda c, n: "-".join(industry[c].split("-")[:n]) if c in industry else None


def group_of(code):
    if MODE == "ind1":
        return lvl(code, 1)
    if MODE == "ind2":
        return lvl(code, 2)
    if MODE == "tier":
        return tier.get(code)
    if MODE == "ind1xtier":
        a, b = lvl(code, 1), tier.get(code)
        return f"{a}|{b}" if a and b else a          # 无分层时退回纯行业，不丢样本
    raise SystemExit(f"未知分组 {MODE}")


rows = []
with open(SRC, newline="", encoding="utf-8") as fh:
    reader = csv.DictReader(fh)
    fields = reader.fieldnames
    for r in reader:
        rows.append(r)
print(f"读入 {len(rows):,} 行")

# ---- 逐年扩窗估计 f_g：第 Y 年只用 < Y-01-01 的观测 ----
hist = collections.defaultdict(list)          # group -> [(date, pv), ...] 按时间序
for r in rows:
    g = group_of(r["security_code"])
    if not g:
        continue
    try:
        pv = float(r["valuation_ratio"])
    except (TypeError, ValueError):
        continue
    hist[g].append((r["date"], pv, r["security_code"]))
for g in hist:
    hist[g].sort()

years = sorted({r["date"][:4] for r in rows})
start_year = str(int(years[0]) + BURN_IN_YEARS)
factors = {}                                   # (year, group) -> f
for y in years:
    for g, seq in hist.items():
        if y < start_year:
            factors[(y, g)] = 1.0
            continue
        cut = bisect.bisect_left(seq, (f"{y}-01-01",))
        window = seq[:cut]
        if len(window) < MIN_OBS or len({c for _, _, c in window}) < MIN_CODES:
            factors[(y, g)] = 1.0
            continue
        factors[(y, g)] = statistics.median(pv for _, pv, _ in window)

active = sum(1 for k, v in factors.items() if v != 1.0)
print(f"分组 {MODE}：{len(hist)} 组｜逐年因子 {len(factors)} 个，其中生效 {active} 个"
      f"（预热到 {start_year} 年）")
sample_year = years[-1]
sm = sorted(((g, factors[(sample_year, g)]) for g in hist if (sample_year, g) in factors),
            key=lambda kv: -kv[1])
print(f"  {sample_year} 年的因子（前 5 / 后 5）：")
for g, f in sm[:5] + sm[-5:]:
    print(f"     {f:>6.2f}  {g}")

# ---- 应用 ----
out, changed = [], 0
for r in rows:
    g = group_of(r["security_code"])
    f = factors.get((r["date"][:4], g), 1.0) if g else 1.0
    if f != 1.0:
        for k in ("intrinsic_value", "band_low", "band_high"):
            if r.get(k):
                try:
                    r[k] = f"{float(r[k]) * f:.6f}"
                except ValueError:
                    pass
        try:
            r["valuation_ratio"] = f"{float(r['valuation_ratio']) / f:.6f}"
            changed += 1
        except (TypeError, ValueError):
            pass
    out.append(r)
with open(DST, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=fields)
    w.writeheader()
    w.writerows(out)
print(f"已写 {DST}：{len(out):,} 行，其中 {changed:,} 行被校准（{changed / len(out) * 100:.0f}%）")
