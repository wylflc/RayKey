"""银行/保险股利折现覆盖（工作流 §6.5.1 第 4 条）：按金融资本型口径给银行重算估值带，其余股票逐位不动。

**动机**（回测日志 §12.30）：现行批量历史带对银行用的是通用 DCF、L2 分档 `r=10%`，
而由 `PB=(ROE−g)/(COE−g)` 反解出的**市场隐含 COE 中位 17.0%**（2011 年起长期 16.5%~22.6%），
非银行只有 7.7%。用 10% 折现一门市场要求 17% 回报的生意，数学上必然恒判「便宜」——
实测银行有 **90% 的在册交易日** `P/V ≤ 0.90`，其中 72% 的月度观测落在 `P/V < 0.60`。

旧 §6.5.2.1 曾写明「同业隐含 COE 中位数优先——A 股银行长期以 PB<1 交易，隐含 COE
显著高于教科书 ERP，用低 ERP 会系统性地把银行判成低估」，但该条只作用于 J 类逐票建档，
**从未作用于批量历史带**。本脚本把它补上。

三种口径（都只改银行行）：
  fixed:COE   PB* = (roe0 − g)/(COE − g)，COE 为给定常数
  peer        COE 取**滚动窗口内同业隐含 COE 的中位**，窗口严格早于当日（分布不是当日点位，
              合乎 §6.3 的价格独立性硬约束）
  pbhist      PB* 直接取该行**滚动窗口内自身 PB 的中位**，完全不经 ROE
  divspread:RP  股利折现：`V = 近 12 个月每股现金分红 ÷ (十年国债 + RP)`，
              即「股息率要比国债高出 RP 才算合理价」。实测（§12.31）该口径的
              股息率−国债利差在全历史五档上单调（其后三年 −0.8%/+1.3%/+3.0%/+7.9%/+11.2%，
              三年为正比例 47%/57%/67%/83%/90%），是银行组唯一单调的候选

  ri:COE|peer   **剩余收益**（OI-072 候选②，研究口径）：`V = BV0 + Σ_{t=1..10} (ROE_t − COE)·BV_{t−1}/(1+COE)^t + 终值`，
              ROE 自 roe0 线性衰减到 `ROE_T = min(roe0, COE + 2pp)`（与主模型 ROIC_T = WACC + 2pp 同规），
              BV 按留存 `1 − payout` 滚存，终值 `(ROE_T − COE)·BV_10 / (COE − g_T)`、`g_T = min(3%, ROE_T × 留存)`；
              COE 取常数或 `peer`（滚动三年同业隐含 COE 中位，严格早于当日）。
  ddm:COE|peer  **股利贴现**（OI-072 候选①）：同一条 ROE/BV 路径上 `DPS_t = ROE_t·BV_{t−1}·payout`，
              `V = Σ DPS_t/(1+COE)^t + DPS_11/(COE − g_T)/(1+COE)^10`。
              两者都用 ROE/BVPS/派息率而非只用 DPS，能区分「DPS 相同而 ROE 18% vs 7%」的两家银行。

用法：
    python3 rebuild_bank_bands.py <模式> <输出文件> [逐日状态文件]
    模式 = fixed:0.15 | peer | pbhist | divspread:0.02 | ri:0.12 | ri:peer | ddm:0.12 | ddm:peer | ddm:peer:13（第三段 = fade 年数）

第三个可选参数用于把同一口径施加到**别的逐日状态文件**上（例如护城河池与银行的并集）；
银行/保险名单按全市场证券名单（`data/raw/a_share_securities.csv`）用 `divspread_names` 判定，
基本面序列取自第四个参数给的估值带——与池子无关。
"""
import csv, sys, os, bisect, collections, statistics
ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
SECURITIES = f"{ROOT}/data/raw/a_share_securities.csv"
BANDS = f"{ROOT}/data/processed/a_share_historical_valuation_bands_pit116.csv"
DAILY = f"{ROOT}/data/processed/a_share_historical_valuation_daily_pit116.csv"
if len(sys.argv) > 3:
    DAILY = sys.argv[3]
if len(sys.argv) > 4:
    BANDS = sys.argv[4]
# **两个缺省输入已于 2026-08-14 的 §12.41 清理中被删**（`*_pit116.csv` 命中删除模式）。
# 缺了 BANDS 时 `fundamentals()` 对每一行都返回 None，于是**每一条银行行都被静默丢弃**——
# 银行占面板 41/211，丢光了读数照样跑得出来，正是本仓库反复踩的那类静默失效（§13 第 3 条）。
# 故这里硬失败，并允许用第 4 个参数指定任意一份含 bps/roe0/payout 的带文件。
for _p, _what in ((DAILY, "逐日状态"), (BANDS, "估值带")):
    if not os.path.exists(_p):
        sys.exit(f"缺少{_what}文件：{_p}\n"
                 f"用法：rebuild_bank_bands.py <模式> <输出> [逐日状态] [估值带]")
WINDOW_DAYS = 1095          # 滚动窗口三年
G_CAP = 0.03                # 终值增长上限，与主模型一致

mode = sys.argv[1] if len(sys.argv) > 1 else "peer"
OUT = sys.argv[2] if len(sys.argv) > 2 else f"{ROOT}/data/processed/vd_pit116_bkpeer.csv"

name = {}
for r in csv.DictReader(open(SECURITIES, encoding="utf-8-sig")):
    name[r["security_code"].zfill(6)] = r["security_name"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from divspread_names import is_divspread_financial   # v4.56：银行＋保险同一判定（OI-085 用户裁定①）
def is_bank(c):
    return is_divspread_financial(c, name.get(c, ""))
BANKS = {c for c in name if is_bank(c)}
print(f"银行与保险 {len(BANKS)} 只（保险按 divspread_names.INSURER_CODES）｜模式 {mode}")

# ---- 每只银行按可得日排列的 (bps, roe0, payout) ----
seq = collections.defaultdict(list)
for r in csv.DictReader(open(BANDS, encoding="utf-8")):
    if r["security_code"] not in BANKS:
        continue
    av = r.get("available_at") or ""
    if len(av) != 10:
        continue
    def num(k):
        try:
            v = float(r[k]); return v if v == v else None
        except (KeyError, TypeError, ValueError):
            return None
    seq[r["security_code"]].append((av, num("bps"), num("roe0"), num("payout")))
for c in seq:
    seq[c].sort(key=lambda x: x[0])
KEYS = {c: [x[0] for x in seq[c]] for c in seq}

def fundamentals(c, day):
    ks = KEYS.get(c)
    if not ks:
        return None
    i = bisect.bisect_right(ks, day) - 1
    return seq[c][i] if i >= 0 else None

def growth(roe0, payout):
    return min(G_CAP, roe0 * (1 - (payout if payout is not None else 0.30)))

# ---- 第一遍：逐（银行,交易日）算隐含 COE 与 PB，供滚动窗口取中位 ----
# 只有 peer / pbhist / *:peer 模式用得到；divspread（§6.7 第 3 步生产模式）跳过这遍 2 GB 全读。
_needs_peer_pass = mode == "peer" or mode.startswith("pbhist") or ":peer" in mode
hist_coe = []          # (日期, 隐含COE)  全体银行汇总，按日期排序
hist_pb = collections.defaultdict(list)   # 代码 -> [(日期, PB)]
for r in (csv.DictReader(open(DAILY, encoding="utf-8")) if _needs_peer_pass else ()):
    c = r["security_code"]
    if c not in BANKS:
        continue
    d = r["date"]
    try:
        px = float(r["close"])
    except (TypeError, ValueError):
        continue
    f = fundamentals(c, d)
    if not f:
        continue
    _, bps, roe0, payout = f
    if not bps or bps <= 0 or roe0 is None or roe0 <= 0 or px <= 0:
        continue
    pb = px / bps
    if not (0.05 < pb < 30):
        continue
    hist_pb[c].append((d, pb))
    g = growth(roe0, payout)
    coe = (roe0 - g) / pb + g
    if 0.03 < coe < 0.60:
        hist_coe.append((d, coe))
hist_coe.sort()
COE_D = [x[0] for x in hist_coe]
for c in hist_pb:
    hist_pb[c].sort()
print(f"隐含 COE 观测 {len(hist_coe):,}", flush=True)

def _shift(day, days):
    from datetime import date, timedelta
    return (date.fromisoformat(day) - timedelta(days=days)).isoformat()

_coe_cache = {}
def peer_coe(day):
    """滚动窗口内同业隐含 COE 的中位；窗口严格早于当日。"""
    if day in _coe_cache:
        return _coe_cache[day]
    hi = bisect.bisect_left(COE_D, day)                  # 严格早于当日
    lo = bisect.bisect_left(COE_D, _shift(day, WINDOW_DAYS))
    v = statistics.median(x[1] for x in hist_coe[lo:hi]) if hi - lo >= 60 else None
    _coe_cache[day] = v
    return v

def own_pb(c, day):
    s = hist_pb.get(c)
    if not s:
        return None
    ds = [x[0] for x in s]
    hi = bisect.bisect_left(ds, day)
    lo = bisect.bisect_left(ds, _shift(day, WINDOW_DAYS))
    return statistics.median(x[1] for x in s[lo:hi]) if hi - lo >= 60 else None

FIXED = float(mode.split(":")[1]) if mode.startswith("fixed:") else None
PATH_MODE = mode.split(":")[0] if mode.startswith(("ri:", "ddm:")) else None      # OI-072 候选：ri / ddm
PATH_COE = None
FADE_YEARS = 10
if PATH_MODE:
    _parts = mode.split(":")
    PATH_COE = None if _parts[1] == "peer" else float(_parts[1])
    if len(_parts) > 2:                       # 第三段 = fade 年数（平台检查用，如 ddm:peer:13）
        FADE_YEARS = int(_parts[2])
TERMINAL_EXCESS = 0.02        # ROE_T = min(roe0, COE + 2pp)，与主模型 ROIC_T = WACC + 2pp 同规


def roe_bv_path(bps, roe0, payout, coe):
    """剩余收益／DDM 共用的 ROE、BV 路径：ROE 自 roe0 线性衰减到 ROE_T，BV 按留存滚存。
    返回 (逐年 (roe_t, bv_prev) 列表, roe_T, g_T, bv_N)。"""
    b = 1.0 - (payout if payout is not None else 0.30)
    b = min(max(b, 0.0), 1.0)
    roe_T = min(roe0, coe + TERMINAL_EXCESS)
    g_T = min(G_CAP, roe_T * b)
    path = []
    bv = bps
    for t in range(1, FADE_YEARS + 1):
        roe_t = roe0 + (roe_T - roe0) * t / FADE_YEARS
        path.append((roe_t, bv))
        bv = bv * (1.0 + roe_t * b)
    return path, roe_T, g_T, bv, b


def ri_value(bps, roe0, payout, coe):
    """剩余收益：V = BV0 + Σ (ROE_t − COE)·BV_{t−1}/(1+COE)^t + (ROE_T − COE)·BV_N/(COE − g_T)/(1+COE)^N。"""
    path, roe_T, g_T, bv_N, _b = roe_bv_path(bps, roe0, payout, coe)
    if coe - g_T < 0.02:
        return None
    pv = sum((roe_t - coe) * bv_prev / (1.0 + coe) ** t for t, (roe_t, bv_prev) in enumerate(path, start=1))
    terminal = (roe_T - coe) * bv_N / (coe - g_T) / (1.0 + coe) ** FADE_YEARS
    return bps + pv + terminal


def ddm_value(bps, roe0, payout, coe):
    """股利贴现：同一路径上 DPS_t = ROE_t·BV_{t−1}·payout，终值 DPS_{N+1}/(COE − g_T)。"""
    path, roe_T, g_T, bv_N, b = roe_bv_path(bps, roe0, payout, coe)
    pay = 1.0 - b
    if coe - g_T < 0.02 or pay <= 0:
        return None
    pv = sum(roe_t * bv_prev * pay / (1.0 + coe) ** t for t, (roe_t, bv_prev) in enumerate(path, start=1))
    terminal = roe_T * bv_N * pay / (coe - g_T) / (1.0 + coe) ** FADE_YEARS
    return pv + terminal
RP = float(mode.split(":")[1]) if mode.startswith("divspread:") else None

# ---- 股利折现口径要用的两组序列 ----
RFS = []
if RP is not None:
    for r in csv.DictReader(open(f"{ROOT}/data/reference/cost_of_equity_inputs.csv", encoding="utf-8")):
        try:
            RFS.append((r["observed_on"], float(r["risk_free_rate"])))
        except (TypeError, ValueError):
            pass
    RFS.sort()
RFD = [x[0] for x in RFS]

DIV = collections.defaultdict(list)
if RP is not None:
    import glob as _glob
    for f in _glob.glob(f"{ROOT}/data/raw/corporate_actions/*.csv"):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            d = r.get("ex_dividend_date") or ""
            if len(d) != 10:
                continue
            try:
                v = float(r.get("cash_per_share") or 0)
            except ValueError:
                v = 0.0
            if v > 0:
                DIV[r["security_code"]].append((d, v))
    for c in DIV:
        DIV[c].sort()

def rf_at(day):
    i = bisect.bisect_right(RFD, day) - 1
    return RFS[i][1] if i >= 0 else None

def div_ttm(c, day):
    """近 12 个月已除权的每股现金分红——只回看，无前视。"""
    s = DIV.get(c)
    if not s:
        return 0.0
    ds = [x[0] for x in s]
    lo = _shift(day, 365)
    return sum(x[1] for x in s[bisect.bisect_left(ds, lo):bisect.bisect_right(ds, day)])

# ---- 第二遍：重写银行行 ----
n_rewritten = n_kept = n_dropped = 0
pb_star = []
with open(DAILY, encoding="utf-8") as fi, open(OUT, "w", encoding="utf-8", newline="") as fo:
    rd = csv.DictReader(fi)
    w = csv.DictWriter(fo, fieldnames=rd.fieldnames)
    w.writeheader()
    for r in rd:
        c = r["security_code"]
        if c not in BANKS:
            w.writerow(r); n_kept += 1; continue
        d = r["date"]
        try:
            px = float(r["close"])
        except (TypeError, ValueError):
            n_dropped += 1; continue
        f = fundamentals(c, d)
        if not f or px <= 0:
            n_dropped += 1; continue
        _, bps, roe0, payout = f
        if not bps or bps <= 0:
            n_dropped += 1; continue
        if RP is not None:
            r10 = rf_at(d); dv = div_ttm(c, d)
            if r10 is None or dv <= 0: n_dropped += 1; continue
            v = dv / (r10 + RP)
            if v <= 0: n_dropped += 1; continue
            pb_star.append(v / bps)
            r["intrinsic_value"] = f"{v:.4f}"
            r["band_low"] = f"{v*0.9:.4f}"
            r["band_high"] = f"{v*1.1:.4f}"
            r["valuation_ratio"] = f"{px/v:.4f}"
            r["upside_to_low"] = f"{v*0.9/px-1:.4f}"
            if "pv_equity" in r: r["pv_equity"] = f"{px/v:.4f}"   # v4.62：股利折现无企业价值口径，两列同值
            if "ev_ps" in r: r["ev_ps"] = ""
            w.writerow(r); n_rewritten += 1; continue
        if PATH_MODE:
            if roe0 is None or roe0 <= 0: n_dropped += 1; continue
            coe = PATH_COE if PATH_COE is not None else peer_coe(d)
            if coe is None: n_dropped += 1; continue
            v = (ri_value if PATH_MODE == "ri" else ddm_value)(bps, roe0, payout, coe)
            if v is None or v <= 0: n_dropped += 1; continue
            pbs = v / bps
            if not (0.05 < pbs < 15): n_dropped += 1; continue
            pb_star.append(pbs)
            r["intrinsic_value"] = f"{v:.4f}"
            r["band_low"] = f"{v*0.9:.4f}"
            r["band_high"] = f"{v*1.1:.4f}"
            r["valuation_ratio"] = f"{px/v:.4f}"
            r["upside_to_low"] = f"{v*0.9/px-1:.4f}"
            if "pv_equity" in r: r["pv_equity"] = f"{px/v:.4f}"
            if "ev_ps" in r: r["ev_ps"] = ""
            w.writerow(r); n_rewritten += 1; continue
        if mode == "pbhist":
            pbs = own_pb(c, d)
            if pbs is None: n_dropped += 1; continue
        else:
            if roe0 is None or roe0 <= 0: n_dropped += 1; continue
            coe = FIXED if FIXED else peer_coe(d)
            if coe is None: n_dropped += 1; continue
            g = growth(roe0, payout)
            if coe - g < 0.02: n_dropped += 1; continue      # 分母塌陷护栏
            pbs = (roe0 - g) / (coe - g)
        if not (0.05 < pbs < 15):
            n_dropped += 1; continue
        v = bps * pbs
        if v <= 0:
            n_dropped += 1; continue
        pb_star.append(pbs)
        r["intrinsic_value"] = f"{v:.4f}"
        r["band_low"] = f"{v*0.9:.4f}"
        r["band_high"] = f"{v*1.1:.4f}"
        r["valuation_ratio"] = f"{px/v:.4f}"
        r["upside_to_low"] = f"{v*0.9/px-1:.4f}"
        if "pv_equity" in r: r["pv_equity"] = f"{px/v:.4f}"
        if "ev_ps" in r: r["ev_ps"] = ""
        w.writerow(r); n_rewritten += 1
print(f"银行行重写 {n_rewritten:,}｜丢弃 {n_dropped:,}｜非银行原样保留 {n_kept:,}")
if pb_star:
    q = sorted(pb_star)
    print(f"合理 PB* 分位：P10 {q[len(q)//10]:.2f}｜中位 {q[len(q)//2]:.2f}｜P90 {q[len(q)*9//10]:.2f}")
print(f"已写 {OUT}")
