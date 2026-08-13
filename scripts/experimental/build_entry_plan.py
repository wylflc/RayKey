"""从零建仓的次日买入清单（§9.7.2 第 3、5 步）。

排序按 `P/V` 升序，逐个检查与**已选**标的的 252 日相关性（>0.85 跳过），至多下扫 40 名；
每只买一档（净资产 1%），按手向下取整；一手金额 > 一档者按 §9.7.3 当次买一手、其后 round(x)−1 次合格跳过。
"""
import csv, json, collections, statistics, math, os

ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
S = "/private/tmp/claude-501/-Users-yaleiwang-WorkSpace-AgentLab-RayKey/81d2c992-2d15-4712-a049-e294cf756ff3/scratchpad"
NAV = 4_500_000.0
TRANCHE = NAV * 0.01
BUY_LINE, MAX_CORR, SCAN_DEPTH, LOT = 1.63, 0.85, 40, 100

rows = json.load(open(f"{S}/scan_rows.json", encoding="utf-8"))

# ---- 252 日收益率序列（本地库，止于 2026-08-07；相关性对 4 日陈旧不敏感） ----
ret = {}
for r in rows:
    f = f"{ROOT}/data/raw/ohlcv/{r['code']}.csv"
    if not os.path.exists(f):
        continue
    cl = [float(x["close"]) for x in csv.DictReader(open(f, encoding="utf-8")) if x.get("close")][-253:]
    if len(cl) >= 120:
        ret[r["code"]] = [cl[i] / cl[i - 1] - 1 for i in range(1, len(cl))]


def corr(a, b):
    x, y = ret.get(a), ret.get(b)
    if not x or not y:
        return 0.0
    n = min(len(x), len(y))
    x, y = x[-n:], y[-n:]
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x)); sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((u - mx) * (v - my) for u, v in zip(x, y)) / (sx * sy)


def tier(pv):
    if pv is None: return "无法估值"
    if pv > 1.32: return "高估"
    if pv > 1.10: return "较高估"
    if pv >= 0.90: return "中性"
    return "低估" if pv <= 1 / 1.4 else "较低估"


for r in rows:
    r["tier_now"] = tier(r["pv"])

elig = [r for r in rows if r["pv"] is not None and r["pv"] <= BUY_LINE and r["trend"] is True]
elig.sort(key=lambda r: r["pv"])
print(f"合格集：P/V ≤ {BUY_LINE} 的 {sum(1 for r in rows if r['pv'] is not None and r['pv']<=BUY_LINE)} 只，"
      f"其中同时满足 收>MA20>MA60 的 **{len(elig)} 只**")

picked, skipped = [], []
for r in elig[:SCAN_DEPTH]:
    worst = max((corr(r["code"], p["code"]) for p in picked), default=0.0)
    if worst > MAX_CORR:
        who = max(picked, key=lambda p: corr(r["code"], p["code"]))
        skipped.append((r, worst, who["name"]))
        continue
    picked.append(r)

cash = NAV
plan = []
for r in picked:
    px = r["px"]
    lot_amt = px * LOT
    if lot_amt <= TRANCHE:
        lots = int(TRANCHE // lot_amt)
        cool = 0
    else:
        lots = 1
        cool = round(lot_amt / TRANCHE) - 1
    amt = lots * lot_amt
    if amt > cash:
        continue
    cash -= amt
    plan.append(dict(r, lots=lots, shares=lots * LOT, amt=amt, cool=cool))

print(f"下扫 {min(SCAN_DEPTH,len(elig))} 名｜相关性剔除 {len(skipped)} 只｜实际买入 {len(plan)} 只")
print(f"投入 {(NAV-cash)/1e4:,.1f} 万 / {NAV/1e4:,.0f} 万（仓位 {(NAV-cash)/NAV*100:.1f}%），余现金 {cash/1e4:,.1f} 万\n")
print(f"{'序':>3} {'代码':<7}{'名称':<9}{'档':<5}{'策略':<22}{'现价':>9}{'合理价区间':>19}{'P/V':>6}{'手数':>5}{'股数':>7}{'金额(万)':>9}{'冷却':>5}")
for i, p in enumerate(plan, 1):
    lo, hi = p["iv"] * 0.9, p["iv"] * 1.1
    print(f"{i:>3} {p['code']:<7}{p['name']:<9}{p['tier_now']:<5}{(p['strat'] or '')[:20]:<22}{p['px']:>9.2f}"
          f"{f'{lo:.2f}-{hi:.2f}':>19}{p['pv']:>6.2f}{p['lots']:>5}{p['shares']:>7}{p['amt']/1e4:>9.2f}"
          f"{('跳'+str(p['cool'])+'次' if p['cool'] else '—'):>7}")
if skipped:
    print("\n相关性 >0.85 被跳过：")
    for r, cv, who in skipped:
        print(f"  {r['name']:<9} P/V {r['pv']:.2f}｜与已选 {who} 相关 {cv:.2f}")
json.dump([{k: v for k, v in p.items() if k != 'trend'} for p in plan], open(f"{S}/plan.json", "w"), ensure_ascii=False)
json.dump(rows, open(f"{S}/scan_rows2.json", "w"), ensure_ascii=False)
