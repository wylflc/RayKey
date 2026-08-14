"""按 §9.7 采纳口径跑一次全池扫描，并给出次日买入清单。四段合一。

**这是四个一次性脚本的合并**（2026-08-13 写于临时目录，2026-08-14 并入本文件）：
`fetch_recent_klines` / `daily_scan_v290` / `build_entry_plan` / `render_pool_model_bands`。
四段是一条流水线，分开放既要手工串联、又各自硬编码了临时目录路径，跨会话就跑不起来。

⚠ **与生产入口的关系（必须知道）**：`scripts/screen_daily_volume_price_signals.py` 才是
§8 成文的每日扫描入口，它产出 §9.7 需要的三个量（收盘、MA20/MA60、252 日相关性）。
本脚本**另起一套**算了同样的量，外加 §9.7 的排序/去相关/定档执行。两者口径重叠但实现独立，
**已登记为 OI-051**——在合并之前，任何一方改了口径都要手动同步另一方。

口径一律来自 `docs/000_Ashare_workflow.md`，本脚本不另立标准：
  买入线 `P/V ≤ 1.63`｜走势 `收 > MA20 > MA60`｜按 `P/V` 升序｜相关性 ≤0.85（252 日）｜下扫至多 40 名
  一档 = 当日净资产 × 1.0%｜整手｜一手超一档走 §9.7.3 比例冷却｜无持仓上限

两处口径细节：
  * **走势闸门用前复权序列**（收盘与均线同尺度，除息不产生假信号）；
  * **`P/V` 用未复权现价 ÷ 当日带**（带已按 §11.3 做过 −D 调整，两侧同为未复权）。

行情走公开接口，不涉及任何凭据。用法：

    python3 scripts/experimental/daily_scan_adopted.py --as-of 2026-08-13 --nav 4500000
    python3 scripts/experimental/daily_scan_adopted.py --as-of 2026-08-13 --nav 4500000 --render-pool
"""
import argparse
import collections
import csv
import glob
import json
import math
import statistics
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POOL_CSV = ROOT / "data/processed/a_share_core_valuation_pool.csv"
POOL_MD = ROOT / "data/processed/000_a_share_core_valuation_pool.md"
OHLCV = ROOT / "data/raw/ohlcv"

BUY_LINE, SELL_LINE = 1.63, 1.10
MAX_CORR, SCAN_DEPTH, LOT = 0.85, 40, 100
TRANCHE_PCT = 0.01
RISK_PREMIUM = 0.02
TIER_EDGES = ((1.32, "高估"), (1.10, "较高估"), (0.90, "中性"))

_num = lambda s: float(s) if s not in ("", "None", "nan", None) else None


def sym(code: str) -> str:
    """交易所前缀。北交所含 43/83/87/92 开头与 4/8/9 打头两类。"""
    if code[0] == "6":
        return "sh" + code
    if code[0] in "489" or code[:2] in ("43", "83", "87", "92"):
        return "bj" + code
    return "sz" + code


# ---------------------------------------------------------------- ① 前复权日线
def fetch_klines(codes, bars: int):
    """近端前复权日线。本地库每日滞后，走势闸门要算到当日，故这一段必须联网。"""
    def one(code):
        url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
               f"param={sym(code)},day,,,{bars},qfq")
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8", "ignore"))
            block = payload["data"][sym(code)]
            rows = block.get("qfqday") or block.get("day") or []
            return code, [(r[0], float(r[2])) for r in rows if len(r) >= 3]
        except Exception:
            return code, []

    out = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for code, rows in pool.map(one, codes):
            out[code] = sorted(rows)
    return out


# ---------------------------------------------------------------- ② 当日未复权现价
def fetch_quotes(codes):
    out = {}
    for i in range(0, len(codes), 40):
        query = ",".join(sym(c) for c in codes[i:i + 40])
        try:
            with urllib.request.urlopen(f"https://qt.gtimg.cn/q={query}", timeout=25) as resp:
                text = resp.read().decode("gbk", "ignore")
        except Exception:
            continue
        for segment in text.split(";"):
            if '="' not in segment:
                continue
            parts = segment.split('"')[1].split("~")
            if len(parts) > 4:
                try:
                    out[parts[2]] = (float(parts[3]), parts[30] if len(parts) > 30 else "")
                except (ValueError, IndexError):
                    pass
    return out


# ---------------------------------------------------------------- ③ 估值带 + P/V
def load_bands(path: Path, as_of: str):
    """取 `available_at ≤ 今日` 的最新一条——**不能用报告期排序**，未披露的带不可用。"""
    latest = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("status") not in (None, "", "ok"):
                continue
            avail = row.get("band_available_at") or row.get("available_at") or ""
            if len(avail) == 10 and avail <= as_of:
                code = row["security_code"]
                if code not in latest or avail >= latest[code][0]:
                    latest[code] = (avail, row)
    return {c: r for c, (_, r) in latest.items()}


def bank_intrinsic(code: str, as_of: str, rf: float):
    """§12.31 银行股利折现：`V = 近 12 个月每股现金分红 ÷ (十年国债 + 2%)`。"""
    total, lo = 0.0, f"{int(as_of[:4]) - 1}{as_of[4:]}"
    for path in glob.glob(str(ROOT / "data/raw/corporate_actions/*.csv")):
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("security_code") != code:
                    continue
                day = row.get("ex_dividend_date") or ""
                value = _num(row.get("cash_per_share")) or 0
                if len(day) == 10 and lo < day <= as_of and value > 0:
                    total += value
    return total / (rf + RISK_PREMIUM) if total > 0 else None


def tier_of(pv):
    if pv is None:
        return "无法估值"
    for edge, name in TIER_EDGES:
        if pv > edge:
            return name
    return "低估" if pv <= 1 / 1.4 else "较低估"


# ---------------------------------------------------------------- ④ 相关性与建仓计划
def returns_252(codes):
    out = {}
    for code in codes:
        path = OHLCV / f"{code}.csv"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            closes = [float(r["close"]) for r in csv.DictReader(fh) if r.get("close")][-253:]
        if len(closes) >= 120:
            out[code] = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    return out


def correlation(rets, a, b):
    xs, ys = rets.get(a), rets.get(b)
    if not xs or not ys:
        return 0.0
    n = min(len(xs), len(ys))
    xs, ys = xs[-n:], ys[-n:]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx = math.sqrt(sum((v - mx) ** 2 for v in xs))
    sy = math.sqrt(sum((v - my) ** 2 for v in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", required=True, help="信号日（交易日），YYYY-MM-DD")
    ap.add_argument("--nav", type=float, required=True, help="当日净资产，用于定一档 = NAV × 1%%")
    ap.add_argument("--bands", type=Path, required=True,
                    help="模型带表（build_historical_valuation_bands.py 的产物）")
    ap.add_argument("--rf", type=float, default=0.017114, help="十年国债，银行股利折现用")
    ap.add_argument("--bars", type=int, default=90)
    ap.add_argument("--render-pool", action="store_true",
                    help="同时重出 data/processed/000_a_share_core_valuation_pool.md")
    args = ap.parse_args()

    pool = list(csv.DictReader(POOL_CSV.open(encoding="utf-8")))
    codes = [r["security_code"] for r in pool]
    info = {r["security_code"]: r for r in pool}
    tranche = args.nav * TRANCHE_PCT

    klines = fetch_klines(codes, args.bars)
    quotes = fetch_quotes(codes)
    bands = load_bands(args.bands, args.as_of)
    stamp = next((v[1] for v in quotes.values() if v[1]), "—")
    print(f"现价 {len(quotes)}/{len(codes)} 只（时间戳样本 {stamp}）｜"
          f"日线 ≥60 根 {sum(1 for v in klines.values() if len(v) >= 60)} 只｜带 {len(bands)} 只")

    is_bank = lambda c: (lambda n: "银行" in n or n.endswith("行") or "农商" in n)(info[c]["security_name"])
    rows = []
    for code in codes:
        price = quotes.get(code, (None, ""))[0]
        closes = [c for _, c in klines.get(code, [])]
        ma20 = ma60 = trend = None
        if len(closes) >= 60:
            ma20, ma60 = statistics.mean(closes[-20:]), statistics.mean(closes[-60:])
            trend = closes[-1] > ma20 > ma60
        intrinsic = bank_intrinsic(code, args.as_of, args.rf) if is_bank(code) else None
        source = "股利折现" if intrinsic else None
        if intrinsic is None and code in bands:
            intrinsic = _num(bands[code].get("intrinsic_value"))
            source = f"DCF·模型带（{bands[code].get('report_date', '')}）"
        pv = price / intrinsic if price and intrinsic and intrinsic > 0 else None
        rows.append(dict(code=code, name=info[code]["security_name"], tier=info[code]["quality_tier"],
                         strat=info[code].get("strategy_tag") or "", px=price, iv=intrinsic,
                         src=source, pv=pv, trend=trend, tier_now=tier_of(pv)))

    eligible = sorted((r for r in rows if r["pv"] is not None and r["pv"] <= BUY_LINE and r["trend"]),
                      key=lambda r: r["pv"])
    n_pv = sum(1 for r in rows if r["pv"] is not None and r["pv"] <= BUY_LINE)
    print(f"P/V ≤ {BUY_LINE} 的 {n_pv} 只；再过 收>MA20>MA60 的 **{len(eligible)} 只**")

    rets = returns_252([r["code"] for r in eligible])
    picked, dropped = [], []
    for cand in eligible[:SCAN_DEPTH]:
        worst = max((correlation(rets, cand["code"], p["code"]) for p in picked), default=0.0)
        if worst > MAX_CORR:
            who = max(picked, key=lambda p: correlation(rets, cand["code"], p["code"]))
            dropped.append((cand, worst, who["name"]))
            continue
        picked.append(cand)

    cash, plan = args.nav, []
    for r in picked:
        lot_amount = r["px"] * LOT
        lots = int(tranche // lot_amount) if lot_amount <= tranche else 1
        cooldown = 0 if lot_amount <= tranche else round(lot_amount / tranche) - 1
        amount = lots * lot_amount
        if lots <= 0 or amount > cash:
            continue
        cash -= amount
        plan.append(dict(r, lots=lots, shares=lots * LOT, amt=amount, cool=cooldown))

    print(f"相关性剔除 {len(dropped)} 只｜买入 {len(plan)} 只｜"
          f"投入 {(args.nav - cash) / 1e4:,.1f} 万（仓位 {(args.nav - cash) / args.nav * 100:.1f}%）"
          f"｜余现金 {cash / 1e4:,.1f} 万\n")
    print(f"{'序':>3} {'代码':<7}{'名称':<10}{'档位':<6}{'现价':>9}{'合理价区间':>19}{'P/V':>6}"
          f"{'股数':>7}{'金额(万)':>9}{'冷却':>7}")
    for i, p in enumerate(plan, 1):
        band = f"{p['iv'] * 0.9:.2f}-{p['iv'] * 1.1:.2f}"
        print(f"{i:>3} {p['code']:<7}{p['name']:<10}{p['tier_now']:<6}{p['px']:>9.2f}{band:>19}"
              f"{p['pv']:>6.2f}{p['shares']:>7}{p['amt'] / 1e4:>9.2f}"
              f"{('跳' + str(p['cool']) + '次' if p['cool'] else '—'):>9}")
    for cand, value, who in dropped:
        print(f"  [剔] {cand['name']} P/V {cand['pv']:.2f}｜与已选 {who} 相关 {value:.2f}")

    if args.render_pool:
        render_pool(rows, {p["code"] for p in plan}, args.as_of, n_pv, len(eligible))
        print(f"\n已重出 {POOL_MD.relative_to(ROOT)}")


def render_pool(rows, bought, as_of, n_pv, n_both):
    """重出估值池 md。**档案带并列保留**，两带偏离 >50% 标 ⚠ 建议进 §7 复核。"""
    order = {"L1": 0, "L2": 1, "L3": 2}
    rows = sorted(rows, key=lambda r: (order.get(r["tier"], 9), r["name"]))
    counts = collections.Counter(r["tier_now"] for r in rows)
    dossier = {r["security_code"]: r for r in csv.DictReader(POOL_CSV.open(encoding="utf-8"))}
    out = [
        "# A股核心估值合格池", "",
        f"生成日期：{as_of}｜现价：**{as_of} 收盘**｜口径 §6.5.7.1 批量模型带", "",
        f"**买卖由 §9.7 唯一决定**：买入线 `P/V ≤ {BUY_LINE}` 且 `收盘 > MA20 > MA60`；"
        f"减持线 `P/V ≥ {SELL_LINE}` 且 `收盘 < MA20`；一档 = 当日净资产 × 1.0%；相关性 ≤ {MAX_CORR}。", "",
        f"**今日扫描**：`P/V ≤ {BUY_LINE}` 的 **{n_pv}** 只；其中同时满足走势条件的 **{n_both}** 只。", "",
        "⚠ **档位标签与买入线已脱节**：档位阈值仍锚在带上（>1.32×中值=高估），而买入线是 "
        f"`P/V ≤ {BUY_LINE}`——**会出现标着「高估」却在买入清单里的行**。档位自 v2.56 起只是展示标签、不决定买卖。", "",
        "**档位分布**：" + "｜".join(f"{k} {counts[k]}" for k in
                                    ("低估", "较低估", "中性", "较高估", "高估", "无法估值") if counts[k]), "",
        "| 代码 | 名称 | 质量 | 档位 | 现价 | 模型带 | P/V | 走势 | 买 | 档案带 | 偏离 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | :---: | :---: | ---: | ---: |",
    ]
    warned = 0
    for r in rows:
        band = f"{r['iv'] * 0.9:.2f}-{r['iv'] * 1.1:.2f}" if r["iv"] else "—"
        src = dossier.get(r["code"], {})
        lo, hi = _num(src.get("fair_price_low")), _num(src.get("fair_price_high"))
        dev = ""
        if r["iv"] and lo and hi and (lo + hi) > 0:
            delta = r["iv"] / ((lo + hi) / 2) - 1
            dev = f"{delta * 100:+.0f}%"
            if abs(delta) > 0.5:
                dev, warned = "⚠" + dev, warned + 1
        mark = "**✓**" if r["code"] in bought else ("✗走势" if r["pv"] is not None
                                                    and r["pv"] <= BUY_LINE else "")
        out.append(f"| {r['code']} | {r['name']} | {r['tier']} | {r['tier_now']} | "
                   f"{r['px']:.2f} | **{band}** | {r['pv']:.2f} | "
                   f"{'✓' if r['trend'] else ('✗' if r['trend'] is False else '—')} | {mark} | "
                   f"{f'{lo:.2f}-{hi:.2f}' if lo and hi else '—'} | {dev} |"
                   if r["px"] and r["pv"] is not None else
                   f"| {r['code']} | {r['name']} | {r['tier']} | {r['tier_now']} | — | {band} | — | — | | | |")
    out += ["", f"**两带偏离 >50% 的有 {warned} 只**——批量模型与逐票档案分歧极大，"
                "§7 复核之前，对这些标的的买入建议应视为**模型口径的机械结论**，不等于已复核的投资判断。"]
    POOL_MD.write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
