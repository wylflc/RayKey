#!/usr/bin/env python3
"""季报行比率锚对 TTM 因子的响应审计（OI-104，回测日志 §12.134）：

按年报行 λ 分组统计季报行 ratio0（nopat_ps ÷ bps_operating）相对同年最新年报行的同向／冻结／反向占比、
`f>1.2` 且 `V/BPS_op`（股本基准无关）跌超 10% 的行数、相邻带 |ΔlnV| 分布，并打印神火／钢研高纳／万华／乐鑫四个例子。

用法：
    python3 scripts/experimental/quarterly_anchor_response_audit.py <bands.csv> <codes.txt>

`codes.txt` 每行一个代码（例：v6b 面板的 287 代码）；bands 为 build_historical_valuation_bands.py 的 --out-bands 产物。
影子验证重跑时对 BASE 与 B2 各跑一次，读数与 §12.134 机制读数表同口径。
"""
import csv, math, statistics as st, sys
from collections import Counter
def num(x):
    try: return float(x)
    except: return None
bands, codes_file = sys.argv[1], sys.argv[2]
codes = {l.strip() for l in open(codes_file) if l.strip()}
rows = []
for r in csv.DictReader(open(bands)):
    if r["security_code"] not in codes or r["status"] != "ok": continue
    V = num(r["intrinsic_value"]); nps = num(r["nopat_ps"]); bo = num(r["bps_operating"]); f = num(r["ttm_factor"]) or 1.0
    rows.append(dict(code=r["security_code"], name=r["security_name"], rd=r["report_date"], path=r["roic_path"], V=V, bo=bo,
                     ratio=(nps / bo) if (nps and bo and bo > 0) else None, lam=num(r["growth_trust"]) or 0.0,
                     pw=num(r["peak_weight"]) or 0.0, tw=num(r["trough_weight"]) or 0.0, f=f))
ann = {(d["code"], int(d["rd"][:4])): d for d in rows if d["rd"].endswith("12-31")}
pairs = []
for d in rows:
    if d["rd"].endswith("12-31") or d["path"] != "growth" or not d["V"] or d["V"] <= 0 or d["f"] <= 0 or not d["ratio"]: continue
    a = ann.get((d["code"], int(d["rd"][:4]) - 1))
    if not a or a["path"] != "growth" or not a["V"] or a["V"] <= 0 or not a["ratio"]: continue
    pairs.append(dict(d, a=a, dlnV=math.log(d["V"] / a["V"]), dr=math.log(d["ratio"] / a["ratio"]), lnf=math.log(d["f"]),
                      dvb=math.log(d["V"] / a["V"]) - math.log(d["bo"] / a["bo"])))
mat = [p for p in pairs if abs(p["lnf"]) > math.log(1.02)]
print(f"季报 growth 带（v6b、年报可比）{len(pairs)}，|f−1|>2% 的 {len(mat)}")
def pct(n, m): return f"{n}({n / m:.0%})" if m else "0"
tot = Counter()
for lam in (0.0, 0.5, 1.0):
    s = [p for p in mat if p["a"]["lam"] == lam]
    al = sum(1 for p in s if (p["lnf"] > 0 and p["dr"] > 0.01) or (p["lnf"] < 0 and p["dr"] < -0.01))
    fr = sum(1 for p in s if abs(p["dr"]) <= 0.01)
    rv = sum(1 for p in s if (p["lnf"] > 0 and p["dr"] < -0.01) or (p["lnf"] < 0 and p["dr"] > 0.01))
    tot.update(al=al, fr=fr, rv=rv, n=len(s))
    slope = float("nan")
    if len(s) > 5:
        x = [p["lnf"] for p in s]; y = [p["dlnV"] for p in s]; mx, my = st.mean(x), st.mean(y)
        sxx = sum((u - mx) ** 2 for u in x); slope = sum((u - mx) * (v - my) for u, v in zip(x, y)) / sxx
    print(f"  年报 λ={lam}: n={len(s)} 同向 {pct(al, len(s))} 冻结 {pct(fr, len(s))} 反向 {pct(rv, len(s))} | ΔlnV/lnf 斜率 {slope:.2f} | 与 f 同号 {sum(1 for p in s if (p['dlnV'] > 0) == (p['lnf'] > 0)) / max(len(s), 1):.0%}")
print(f"  合计: 同向 {pct(tot['al'], tot['n'])} 冻结 {pct(tot['fr'], tot['n'])} 反向 {pct(tot['rv'], tot['n'])}")
bad = [p for p in pairs if p["f"] > 1.2 and p["dlnV"] < math.log(0.9)]
bad0 = [p for p in bad if p["a"]["lam"] == 0]
vb = [p for p in pairs if p["f"] > 1.2 and p["dvb"] < math.log(0.9)]; vb0 = [p for p in vb if p["a"]["lam"] == 0]
print(f"  [股本基准无关] f>1.2 且 V/BPS_op 跌超 10%: {len(vb)} 行（λ=0 的 {len(vb0)}，其中跌超 30%: {sum(1 for p in vb0 if p['dvb'] < math.log(0.7))}）；f<0.8 且 V/BPS_op 涨超 10%: {sum(1 for p in pairs if p['f'] < 0.8 and p['dvb'] > math.log(1.1))} 行")
print(f"  f>1.2 且 V 跌超 10%: {len(bad)} 行（跌超 30%: {sum(1 for p in bad if p['dlnV'] < math.log(0.7))}）；其中年报 λ=0 的 {len(bad0)} 行（跌超 30%: {sum(1 for p in bad0 if p['dlnV'] < math.log(0.7))}）")
bad_dn = [p for p in pairs if p["f"] < 0.8 and p["dlnV"] > math.log(1.1)]
print(f"  f<0.8 且 V 涨超 10%: {len(bad_dn)} 行")
# 相邻带跳变（同一代码按报告期相邻的 ok 带，全部路径）
bycode = {}
for d in rows:
    if d["V"] and d["V"] > 0: bycode.setdefault(d["code"], []).append(d)
jumps = []
for lst in bycode.values():
    lst.sort(key=lambda d: d["rd"])
    jumps += [abs(math.log(b["V"] / a["V"])) for a, b in zip(lst, lst[1:])]
jumps.sort()
print(f"  相邻带 |ΔlnV|: n={len(jumps)} 中位 {jumps[len(jumps)//2]:.2%} P90 {jumps[int(len(jumps)*0.9)]:.2%} >20% 的 {sum(1 for j in jumps if j > 0.2)}")
want = {("000933", "2026-06-30"), ("600309", "2026-06-30"), ("688018", "2024-09-30"), ("300034", "2026-06-30"), ("600763", "2026-06-30")}
for p in pairs:
    if (p["code"], p["rd"]) in want:
        print(f"  例 {p['name']} {p['rd']}: f={p['f']:.2f} λ_q={p['lam']:.1f} v {p['a']['tw']:.2f}→{p['tw']:.2f} V {p['a']['V']:.2f}→{p['V']:.2f} ({p['dlnV']*100:+.1f}%; 基准无关 V/BPS {p['dvb']*100:+.1f}%)")
