"""§9.7 每日扫描（工作流 v2.90 口径）＋ 从零建仓的次日买入清单。

口径来源一律是 `docs/000_Ashare_workflow.md`，本脚本不另立标准：
  买入线 `P/V ≤ 1.63`｜走势 `收 > MA20 > MA60`｜按 `P/V` 升序｜相关性 ≤0.85（252 日）｜下扫至多 40 名
  一档 = 当日净资产 × 1.0%｜整手｜一手超一档走 §9.7.3 比例冷却｜无持仓上限

两处口径细节：
  * **走势闸门用前复权序列**（收盘与均线同尺度，除息不产生假信号）；
  * **`P/V` 用未复权现价 ÷ 当日带**（带已按 §11.3 做过 −D 调整，两侧同为未复权）。
"""
import csv, json, collections, statistics, bisect, urllib.request, math, sys

ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
S = "/private/tmp/claude-501/-Users-yaleiwang-WorkSpace-AgentLab-RayKey/81d2c992-2d15-4712-a049-e294cf756ff3/scratchpad"
TODAY = "2026-08-13"
NAV = 4_500_000.0
TRANCHE = NAV * 0.01
BUY_LINE = 1.63
SELL_LINE = 1.10
MAX_CORR = 0.85
SCAN_DEPTH = 40
RP = 0.02

num = lambda s: (float(s) if s not in ("", "None", "nan", None) else None)


def sym(c):
    return ("sh" if c[0] == "6" else ("bj" if c[0] in "489" or c[:2] in ("43", "83", "87", "92") else "sz")) + c


# ---------- 池 ----------
POOL = list(csv.DictReader(open(f"{ROOT}/data/processed/a_share_core_valuation_pool.csv", encoding="utf-8")))
CODES = [r["security_code"] for r in POOL]
INFO = {r["security_code"]: r for r in POOL}

# ---------- 今日未复权现价（公开行情接口，无凭据） ----------
RAW = {}
for i in range(0, len(CODES), 40):
    q = ",".join(sym(c) for c in CODES[i:i + 40])
    try:
        with urllib.request.urlopen(f"https://qt.gtimg.cn/q={q}", timeout=25) as r:
            txt = r.read().decode("gbk", "ignore")
    except Exception:
        continue
    for seg in txt.split(";"):
        if '="' not in seg:
            continue
        v = seg.split('"')[1].split("~")
        if len(v) > 4 and v[2] in INFO:
            try:
                RAW[v[2]] = (float(v[3]), v[30] if len(v) > 30 else "")
            except ValueError:
                pass
print(f"现价：{len(RAW)}/{len(CODES)} 只取到，时间戳样本 {list(RAW.values())[0][1] if RAW else '—'}")

# ---------- 前复权序列（走势） ----------
K = collections.defaultdict(list)
for r in csv.DictReader(open(f"{S}/klines.csv", encoding="utf-8")):
    K[r["security_code"]].append((r["date"], float(r["close"])))
for c in K:
    K[c].sort()

# ---------- 估值带：取 available_at ≤ 今日 的最新一条 ----------
BAND = collections.defaultdict(list)
for r in csv.DictReader(open(f"{S}/vb_pool.csv", encoding="utf-8")):
    if r.get("status") != "ok":
        continue
    av = r.get("available_at") or ""
    if len(av) == 10 and av <= TODAY:
        BAND[r["security_code"]].append((av, r))
for c in BAND:
    BAND[c].sort(key=lambda x: x[0])

# ---------- 银行：股利折现 ----------
rf = 0.017114  # 十年国债，data/reference/cost_of_equity_inputs.csv 最新观测 2026-08-07
DIV = collections.defaultdict(list)
import glob
for f in glob.glob(f"{ROOT}/data/raw/corporate_actions/*.csv"):
    for r in csv.DictReader(open(f, encoding="utf-8")):
        d = r.get("ex_dividend_date") or ""
        v = num(r.get("cash_per_share")) or 0
        if len(d) == 10 and v > 0:
            DIV[r["security_code"]].append((d, v))
for c in DIV:
    DIV[c].sort()


def div_ttm(c):
    s = DIV.get(c) or []
    lo = "2025-08-13"
    return sum(v for d, v in s if lo < d <= TODAY)


isbank = lambda c: (lambda n: ("银行" in n) or n.endswith("行") or "农商" in n)(INFO[c]["security_name"])

# ---------- 逐股计算 ----------
rows = []
for c in CODES:
    nm = INFO[c]["security_name"]
    px = RAW.get(c, (None, ""))[0]
    ks = K.get(c) or []
    ma20 = ma60 = None
    trend = None
    if len(ks) >= 60:
        cl = [x[1] for x in ks]
        ma20, ma60 = statistics.mean(cl[-20:]), statistics.mean(cl[-60:])
        trend = cl[-1] > ma20 > ma60
    iv = src = None
    if isbank(c):
        d = div_ttm(c)
        if d > 0:
            iv, src = d / (rf + RP), "股利折现"
    if iv is None:
        b = BAND.get(c)
        if b:
            iv = num(b[-1][1].get("intrinsic_value"))
            if iv is None:
                e, r0 = num(b[-1][1].get("eps0")), None
                iv = None
            src = f"DCF·λ2.0（{b[-1][1]['report_date']}）"
    pv = (px / iv) if (px and iv and iv > 0) else None
    rows.append(dict(code=c, name=nm, tier=INFO[c]["quality_tier"], strat=INFO[c]["strategy_tag"],
                     px=px, iv=iv, src=src, pv=pv, ma20=ma20, ma60=ma60, trend=trend))

have_pv = [r for r in rows if r["pv"] is not None]
print(f"可算 P/V {len(have_pv)}/{len(rows)} 只｜其中银行走股利折现 {sum(1 for r in rows if r['src']=='股利折现')} 只")
json.dump(rows, open(f"{S}/scan_rows.json", "w"), ensure_ascii=False)
print("已写 scan_rows.json")
