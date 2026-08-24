"""给现行估值带并联一条「成长/PEG」通道，只放宽不收紧：`P/V = min(P/V_DCF, P/V_PEG)`。

**动机**（回测日志 §12.31）：现行 DCF 的 `roe0` 是近五年年度 ROE 的中位，结构上向后看，
于是「成长加速中」的公司几乎永远不合格——实测成长股只有 **5.9%** 的在册日 `P/V ≤ 0.90`，
金融股有 90%。用户的判词：「好公司只有在财务数据很差的时候才会跌下来给底部买入的机会……
如果估值模型识别不出这种公司，那将会是只能选出下行期垃圾公司的模型。」

**PEG 通道**：`V_PEG = EPS_ttm × (g × 100) × PEG目标`，即「增速多少就给多少倍 PE」。
`g` 取带里已算好的 `g_trailing`（已实现三年 EPS 复合增速，按可得日入账，无前视）。
本仓库的研报预测字段只有 2024 年起才填（`predict_next_year_eps` 覆盖 2025-2026），
**做不了真正的前瞻 PEG**，故此处用已实现增速作代理——这是本口径最大的让步，须知情。

护栏（缺一不可，否则会把「增速虚高的周期股/一次性损益」放进来）：
  * `eps_ttm > 0` 且 `g` 落在 [g_min, g_max]：负增长与荒谬增速都不给通道
  * 可选 `--min-roe`：ROE 低于此值不给通道（挡住「低质量高增速」）
  * 可选 `--max-pe`：算出来的隐含 PE 超过上限就不给通道（挡住高增速外推）
  * 可选 `--accel`：要求 `roe_ttm` 不低于一年前（四期前）的读数。**这条是 §12.31.4 诊断出来的**：
    PEG 通道新放进来的观测里最拖累的是 2021 年高位的白酒（泸州老窖 −21%、五粮液 −20%、
    山西汾酒 −14%）与周期顶的资源股（盐湖股份 −26%），它们的共同点是**已实现增速很高但正在减速**；
    最好的（海康威视 +59%、美的集团 +44%）则是增速仍在抬升。用「ROE 同比不下滑」区分这两类。

用法：
    python3 add_growth_path.py <PEG目标> <输出文件> [--min-g 0.10] [--max-g 0.60]
                               [--min-roe 0.10] [--max-pe 60] [--only-nonbank]
"""
import csv, sys, os, bisect, collections, argparse
ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
PANEL = f"{ROOT}/data/archive/pit-judgment-2026-08/universe_panel_pit_v2.csv"
BANDS = f"{ROOT}/data/processed/a_share_historical_valuation_bands_pit116.csv"
DAILY = f"{ROOT}/data/processed/a_share_historical_valuation_daily_pit116.csv"

ap = argparse.ArgumentParser()
ap.add_argument("peg", type=float)
ap.add_argument("out")
ap.add_argument("--min-g", type=float, default=0.10)
ap.add_argument("--max-g", type=float, default=0.60)
ap.add_argument("--min-roe", type=float, default=0.0)
ap.add_argument("--max-pe", type=float, default=0.0)
ap.add_argument("--accel", action="store_true", help="要求 roe_ttm 不低于一年前")
ap.add_argument("--only-nonbank", action="store_true")
ap.add_argument("--daily", default=DAILY, help="底稿逐日文件，缺省用现行 DCF 带")
ap.add_argument("--bands", default=BANDS, help="基本面来源带表")
a = ap.parse_args()

name = {r["security_code"]: r["security_name"]
        for r in csv.DictReader(open(PANEL, encoding="utf-8"))}
def is_bank(c):
    n = name.get(c, "")
    return ("银行" in n) or n.endswith("行") or "农商" in n

seq = collections.defaultdict(list)
for r in csv.DictReader(open(a.bands, encoding="utf-8")):
    av = r.get("available_at") or ""
    if len(av) != 10:
        continue
    def num(k):
        try:
            v = float(r[k]); return v if v == v else None
        except (KeyError, TypeError, ValueError):
            return None
    seq[r["security_code"]].append((av, num("eps_ttm"), num("g_trailing"), num("roe_ttm")))
for c in seq:
    seq[c].sort(key=lambda x: x[0])
KEY = {c: [x[0] for x in seq[c]] for c in seq}
def fund(c, d):
    ks = KEY.get(c)
    if not ks:
        return None
    i = bisect.bisect_right(ks, d) - 1
    return seq[c][i] if i >= 0 else None

stats = collections.Counter()
opened = collections.Counter()
with open(a.daily, encoding="utf-8") as fi, open(a.out, "w", encoding="utf-8", newline="") as fo:
    rd = csv.DictReader(fi)
    w = csv.DictWriter(fo, fieldnames=rd.fieldnames)
    w.writeheader()
    for r in rd:
        c = r["security_code"]; d = r["date"]
        try:
            px = float(r["close"]); pv = float(r["valuation_ratio"])
        except (TypeError, ValueError):
            w.writerow(r); stats["原样"] += 1; continue
        if a.only_nonbank and is_bank(c):
            w.writerow(r); stats["银行·原样"] += 1; continue
        f = fund(c, d)
        if not f:
            w.writerow(r); stats["无基本面"] += 1; continue
        _, eps, g, roe = f
        if eps is None or eps <= 0 or g is None:
            w.writerow(r); stats["EPS或g缺"] += 1; continue
        if not (a.min_g <= g <= a.max_g):
            w.writerow(r); stats["g不在区间"] += 1; continue
        if a.min_roe and (roe is None or roe < a.min_roe):
            w.writerow(r); stats["ROE不足"] += 1; continue
        if a.accel:
            ks = KEY.get(c) or []
            i = bisect.bisect_right(ks, d) - 1
            prev = seq[c][i - 4][3] if i >= 4 else None
            if prev is None or roe is None or roe < prev:
                w.writerow(r); stats["ROE同比下滑"] += 1; continue
        pe_star = g * 100 * a.peg
        if a.max_pe and pe_star > a.max_pe:
            w.writerow(r); stats["隐含PE超上限"] += 1; continue
        v_peg = eps * pe_star
        if v_peg <= 0:
            w.writerow(r); stats["V非正"] += 1; continue
        pv_peg = px / v_peg
        if pv_peg < pv:                       # 只放宽不收紧
            r["intrinsic_value"] = f"{v_peg:.4f}"
            r["band_low"] = f"{v_peg*0.9:.4f}"
            r["band_high"] = f"{v_peg*1.1:.4f}"
            r["valuation_ratio"] = f"{pv_peg:.4f}"
            r["upside_to_low"] = f"{v_peg*0.9/px-1:.4f}"
            stats["走PEG通道"] += 1
            opened[c] += 1
        else:
            stats["PEG更贵·维持DCF"] += 1
        w.writerow(r)
tot = sum(stats.values())
print(f"PEG 目标 {a.peg}｜g∈[{a.min_g},{a.max_g}]｜min-roe {a.min_roe}｜max-pe {a.max_pe or '—'}")
for k, v in stats.most_common():
    print(f"  {k:<18}{v:>9,}  {v/tot*100:>5.1f}%")
top = opened.most_common(12)
print("走 PEG 通道最多的股票：" + "｜".join(f"{name.get(c,c)} {n:,}" for c, n in top))
print(f"已写 {a.out}")
