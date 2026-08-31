"""以 **MA60** 而非日收盘作为「上下各一半」的居中判据来校准估值带（用户 2026-08-14）。

理由：日收盘含短期噪声，而「估值是否居中」问的是**中枢**是否居中。
用 MA60 做判据即把噪声先滤掉再判。

两种产物：
  `ma`   —— 因子 `f_g = median(MA60 / V)`；**交易仍用日收盘算 P/V**（实盘按收盘下单）。
  `mapv` —— 在 `ma` 之上，**把 P/V 本身也换成 `MA60 / V'`**，即闸门与排序都走平滑后的估值比。

MA60 直接从逐日状态文件的 `close` 列算，**与 P/V 分子同源**，不引入第二套行情。
逐年扩窗，样本不足退回不校准，预热 5 年。

用法：python3 calib_ma.py <输入> <输出> <ma|mapv>
"""
import bisect, collections, csv, math, statistics, sys

from pathlib import Path
ROOT = str(Path(__file__).resolve().parents[2])
SRC, DST, MODE = sys.argv[1], sys.argv[2], sys.argv[3]
MIN_OBS, MIN_CODES, BURN, WIN = 500, 3, 5, 60

ind = {}
for r in csv.DictReader(open(f"{ROOT}/data/interim/a_share_company_profiles.csv", encoding="utf-8-sig")):
    c = (r.get("security_code") or "").zfill(6)
    if r.get("eastmoney_industry"):
        ind[c] = r["eastmoney_industry"].split("-")[0]

rows = list(csv.DictReader(open(SRC, newline="", encoding="utf-8")))
fields = list(rows[0].keys())

# ---- 逐票 MA60（源自同一张表的 close，保证与 P/V 分子同源）----
by_code = collections.defaultdict(list)
for i, r in enumerate(rows):
    try:
        by_code[r["security_code"]].append((r["date"], float(r["close"]), i))
    except (TypeError, ValueError):
        pass
ma60 = {}
for c, seq in by_code.items():
    seq.sort()
    tot = 0.0
    vals = [v for _, v, _ in seq]
    for j, (_, _, i) in enumerate(seq):
        tot += vals[j]
        if j >= WIN:
            tot -= vals[j - WIN]
        if j >= WIN - 1:
            ma60[i] = tot / WIN
print(f"MA60 覆盖 {len(ma60):,}/{len(rows):,} 行（前 {WIN-1} 根不足窗口）")

# ---- 逐年扩窗因子：median(MA60 / V) ----
hist = collections.defaultdict(list)
for i, r in enumerate(rows):
    g = ind.get(r["security_code"].zfill(6))
    m = ma60.get(i)
    if not g or m is None:
        continue
    try:
        iv = float(r["intrinsic_value"])
    except (TypeError, ValueError):
        continue
    if iv > 0:
        hist[g].append((r["date"], m / iv, r["security_code"]))
for g in hist:
    hist[g].sort()

years = sorted({r["date"][:4] for r in rows})
start = str(int(years[0]) + BURN)
fac = {}
for y in years:
    for g, seq in hist.items():
        if y < start:
            fac[(y, g)] = 1.0
            continue
        cut = bisect.bisect_left(seq, (f"{y}-01-01",))
        w = seq[:cut]
        fac[(y, g)] = (statistics.median(v for _, v, _ in w)
                       if len(w) >= MIN_OBS and len({c for _, _, c in w}) >= MIN_CODES else 1.0)
print(f"{len(hist)} 组｜生效因子 {sum(1 for v in fac.values() if v != 1.0)}/{len(fac)}")
sm = sorted(((g, fac[(years[-1], g)]) for g in hist), key=lambda kv: -kv[1])
print("  末年因子 前3/后3：" + "｜".join(f"{g} {f:.2f}" for g, f in sm[:3] + sm[-3:]))

n = 0
for i, r in enumerate(rows):
    g = ind.get(r["security_code"].zfill(6))
    f = fac.get((r["date"][:4], g), 1.0) if g else 1.0
    try:
        iv = float(r["intrinsic_value"]); close = float(r["close"])
    except (TypeError, ValueError):
        continue
    if iv <= 0 or close <= 0:
        continue
    niv = iv * f
    for k, mult in (("intrinsic_value", f), ("band_low", f), ("band_high", f)):
        if r.get(k):
            try:
                r[k] = f"{float(r[k]) * mult:.6f}"
            except ValueError:
                pass
    num = ma60.get(i) if MODE == "mapv" else close
    if num is None:                      # mapv 下 MA60 不足窗口 → 该行不可判，置空
        r["valuation_ratio"] = ""
    else:
        r["valuation_ratio"] = f"{num / niv:.6f}"
    if f != 1.0:
        n += 1
with open(DST, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
blank = sum(1 for r in rows if not r["valuation_ratio"])
print(f"已写 {DST.split('/')[-1]}：{n:,} 行被校准；P/V 分子 = {'MA60' if MODE=='mapv' else '日收盘'}"
      f"｜空 P/V {blank:,} 行")
