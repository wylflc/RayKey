#!/usr/bin/env python3
"""把业绩预告／快报叠加到生产模型带上（§6.3 第 5 条的执行点）。

为什么需要这一步
----------------
`build_historical_valuation_bands.py` 只读**已披露财报**（`data/raw/financials/`）。
业绩预告与快报公告日虽然早于正式报告，却进不到带——这是 OI-064 登记的缺陷：
§6.3 第 5 条写着「预告与快报……进入锚；快报优先，区间取中值」，但生产链七个脚本
无一读取预告文件，条文从未落地。判例：牧原股份 2026-07-11 预告 H1 首亏 −62 亿，
而生产带到 2026-08-18 仍机械锚在一季报。

预告从哪条通道进模型
--------------------
ROIC 模型的结构是：

    nopat_ps = ratio0 × bps          # ratio0 = 归一化 NOPAT/净资产（稳健锚）
    ev_ps    = DCF(nopat_ps, roic0, g0, wacc, roe_terminal)
    IV       = ev_ps − net_debt_ps

预告给的是**归母净利润**，它通过留存收益改变**净资产**，因此落在 `bps` 这条通道上，
**不动 `ratio0`**。这有三个好处：

1. **与正式报告落地时模型要做的事完全一致**——正式报告同样先改 `bps`。故预告带与
   后来的正式带是同一套算法、同一条通道，输入从预告中值换成实际值而已，会自然收敛。
2. **不重蹈已被回测否决的 `--roe-source ttm`**（§12.14.3：五起点年化全负）。归一化锚
   保持稳健，单个谷底半年不会把周期股的带打穿。
3. **纯机械、可推导**，不需要人工判断。

`net_debt_ps` **不调整**：预告给不出资产负债表（有息负债／超额现金／少数股东权益），
硬估会把一个不可验证的假设混进带里。这一项等正式报告。**该省略使亏损公司的带偏高、
盈利公司的带偏低，方向已知，见输出的 `overlay_note`。**

生产与回测的已知背离（重要）
----------------------------
§6.5.7.1 原本要求「生产 `P/V` 与回测 `valuation_ratio` 逐位一致」。本脚本**有意打破**
这条：回测宇宙没有历史预告面板（`fetch_a_share_earnings_forecasts.py` 只取当前报告期），
无法在历史上复现预告。用户 2026-08-18 裁定：实盘能更快反映最新信息，没有理由不做。

**隔离方式**：本脚本只改**生产**带 `a_share_pool_model_bands_adopted.csv`；
回测输入 `roic_bands.csv` / `roic_daily_raw.csv` / `a_share_daily_states_adopted.csv`
一律不碰。故回测基准不受影响，两侧的差异只存在于「今日生产带」这一层。

数值口径
--------
`intrinsic_value` 对首个参数（盈利输入）**一次齐次**——已数值验证 216 组参数零违反——
故新值 = 旧值 × `scale`，与「按新输入重算 DCF」逐位等价。这样做还避开了带文件四位小数
的舍入：直接用存值重算会引入最大约 0.08% 的误差，而按比例缩放让未叠加的行与叠加前
逐位一致。净负债不参与缩放（它不随利润等比变动）。

用法
----
在 §6.7 建带链的第 4 步（`build_pool_model_bands.py`）之后、
`apply_model_bands_to_dossiers.py` 之前运行。幂等：同一份预告不会被叠加两次。
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intrinsic_value import intrinsic_value  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BAND_LOW_COEF, BAND_HIGH_COEF = 0.90, 1.10
# 叠加后新增的列。`forecast_overlay` 非空即表示本行已被叠加，用于幂等与下游识别。
OVERLAY_COLS = ["forecast_overlay", "forecast_notice_date", "forecast_report_date",
                "forecast_profit_yi", "forecast_source", "pre_overlay_iv",
                "pre_overlay_report_date", "bps_scale", "overlay_note"]


def num(value) -> float | None:
    try:
        f = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def load_financials(fin_dir: Path) -> dict[str, dict[str, dict]]:
    """{代码: {报告期: 行}}，只装载有 `parent_netprofit` 的行。"""
    out: dict[str, dict[str, dict]] = {}
    for path in sorted(fin_dir.glob("*.csv")):
        period = path.stem
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                code = (row.get("security_code") or "").strip()
                if code:
                    out.setdefault(code, {})[period] = row
    return out


MAX_SHARE_LOOKBACK_YEARS = 2   # 只用带的报告期往前两年内的期次推股本（更早的股本可能已因增发送转改变）
MAX_SHARE_DEVIATION = 0.15     # 单期倒推与市值倒推的最大允许偏差
SHARE_CONSISTENCY_TOL = 0.05   # 多期倒推彼此的最大允许离散


def derive_shares(periods: dict[str, dict], band_period: str,
                  market_shares: float | None) -> tuple[float | None, str]:
    """股本 = 归母净利 ÷ 每股收益，**从带的报告期开始往回找，绝不取远期**。

    **这里踩过一次坑**：早期版本按 |EPS| 最大挑期，于是挑到送转与增发之前的远古年报——
    高德红外取到 2006 年报（1.23 亿股，实际约 43 亿）、亿联网络取到 2015 年、
    鼎龙取到 2009 年，`scale` 因此虚增到荒谬量级（高德的带一度被推 +461%）。
    股本随增发／送转变化，**必须取当期口径**。

    `basic_eps` 是加权平均股本口径、`bps` 是期末总股本口径，有股本变动时不完全一致；
    本函数的结果只用于把「利润增量」换算成「每股增量」，该口径差在增量上是二阶量。
    仍与市值倒推的总股本交叉校验，偏差超过 `MAX_SHARE_DEVIATION` 即判不可用。
    """
    cand: list[tuple[str, float]] = []
    for period in sorted(periods, reverse=True):
        if period > band_period or period < _minus_years(band_period, MAX_SHARE_LOOKBACK_YEARS):
            continue
        row = periods[period]
        profit, eps = num(row.get("parent_netprofit")), num(row.get("basic_eps"))
        if profit is None or eps is None or abs(eps) < 0.01:
            continue
        shares = profit / eps
        if shares > 0:
            cand.append((period, shares))
        if len(cand) >= 3:
            break

    # 多期一致 = 可信。远古股本被误取（高德红外那类）表现为**期间彼此不一致**，
    # 故一致性本身就是最好的判据，比与市值倒推对齐更可靠——市值列本身也会不准
    # （判例：电投能源 EPS 倒推 4 期稳定 22.4 亿股，市值倒推给 31.3 亿股）。
    if len(cand) >= 2:
        vals = [s for _, s in cand]
        if max(vals) / min(vals) - 1 <= SHARE_CONSISTENCY_TOL:
            vals.sort()
            return vals[len(vals) // 2], f"{cand[-1][0]}~{cand[0][0]} 共 {len(cand)} 期一致"
    if cand and market_shares and abs(cand[0][1] / market_shares - 1) <= MAX_SHARE_DEVIATION:
        return cand[0][1], f"{cand[0][0]}（与市值倒推一致）"
    if cand:
        return None, (f"股本不稳定：{'／'.join(f'{p} {s/1e8:.2f}亿' for p, s in cand)}"
                      + (f"，市值倒推 {market_shares/1e8:.2f}亿" if market_shares else "，且无市值可校验"))
    if market_shares:
        return market_shares, "市值倒推（无可用 EPS 期）"
    return None, "无 |EPS| ≥ 0.01 的可用报告期，且市值倒推不可得"


def _minus_years(period: str, years: int) -> str:
    try:
        return f"{int(period[:4]) - years}{period[4:]}"
    except ValueError:
        return "0000-00-00"


def dividends_between(actions: list[dict], start: str, end: str) -> float:
    """(start, end] 区间内除权除息的每股现金分红合计（税前）。"""
    total = 0.0
    for row in actions:
        ex = (row.get("ex_dividend_date") or "").strip()[:10]
        if ex and start < ex <= end:
            total += num(row.get("cash_per_share")) or 0.0
    return total


def pick_evidence(code: str, forecasts: dict, express: dict, band_period: str,
                  as_of: str) -> dict | None:
    """选证据：§6.3 第 5 条「快报优先」。只取报告期晚于当前带、且公告日不晚于 as_of 的。"""
    cand = []
    ex = express.get(code)
    if ex and (ex.get("report_date") or "")[:10] > band_period and (ex.get("notice_date") or "")[:10] <= as_of:
        profit = num(ex.get("parent_netprofit"))
        if profit is not None:
            cand.append({"kind": "express", "priority": 0, "profit": profit,
                         "report_date": ex["report_date"][:10], "notice_date": ex["notice_date"][:10],
                         "label": "快报"})
    fc = forecasts.get(code)
    if fc and (fc.get("report_date") or "")[:10] > band_period and (fc.get("notice_date") or "")[:10] <= as_of:
        lo, hi = num(fc.get("predict_amt_lower")), num(fc.get("predict_amt_upper"))
        vals = [v for v in (lo, hi) if v is not None]
        if vals:
            cand.append({"kind": "forecast", "priority": 1, "profit": sum(vals) / len(vals),
                         "report_date": fc["report_date"][:10], "notice_date": fc["notice_date"][:10],
                         "label": f"预告·{fc.get('predict_type') or ''}".rstrip("·")})
    if not cand:
        return None
    cand.sort(key=lambda c: c["priority"])
    return cand[0]


def recompute(band: dict, scale: float) -> tuple[float | None, float, str] | None:
    """返回 (新 ev_ps 或 None, 新 IV, 缩放的量)。

    三条路径都**严格线性于各自的盈利输入**，故直接乘 `scale` 即可，不必重算 DCF：

    - `growth` / `zero_growth`：`nopat_ps = ratio0 × bps` → 企业价值线性 →
      `IV = ev_ps×scale − net_debt_ps`（净负债不缩放，它不随利润等比变动）。
    - `equity_fallback`（无三大报表或金融企业退回的权益口径）：`eps0 = roe0 × bps`，
      直接给出股权价值、不减净负债 → `IV = IV×scale`。

    线性性已数值验证：`intrinsic_value` 对首参数一次齐次（216 组参数零违反），
    故乘 `scale` 与「按新输入重算」逐位等价，且避开了带文件四位小数的舍入误差。
    """
    path = (band.get("roic_path") or "").strip()
    if path == "equity_fallback":
        iv, eps0 = num(band.get("intrinsic_value")), num(band.get("eps0"))
        if iv is None or eps0 is None or eps0 <= 0:
            return None
        return None, iv * scale, "eps0"
    if path in ("growth", "zero_growth"):
        nopat, net_debt = num(band.get("nopat_ps")), num(band.get("net_debt_ps"))
        ev_ps = num(band.get("ev_ps"))
        if ev_ps is None:
            # `zero_growth` 路径不落 `ev_ps`（建带脚本只写 `v_zero_growth = nopat_ps/wacc − net_debt_ps`），
            # 由 IV 反解即可，二者恒等。不反解会把整条路径当成"输入不全"挡掉。
            iv0 = num(band.get("intrinsic_value"))
            if iv0 is not None and net_debt is not None:
                ev_ps = iv0 + net_debt
        if nopat is None or ev_ps is None or net_debt is None or nopat <= 0:
            return None
        ev_new = ev_ps * scale
        return ev_new, ev_new - net_debt, "nopat_ps"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="把业绩预告／快报叠加到生产模型带（§6.3 第 5 条）")
    ap.add_argument("--as-of", required=True, help="信号日（北京时间），只采用公告日不晚于它的证据")
    ap.add_argument("--bands", type=Path, default=ROOT / "data/processed/a_share_pool_model_bands_adopted.csv")
    ap.add_argument("--forecasts", type=Path, default=ROOT / "data/interim/a_share_earnings_forecasts.csv")
    ap.add_argument("--disclosures", type=Path, default=ROOT / "data/interim/a_share_report_disclosures.csv")
    ap.add_argument("--financials-dir", type=Path, default=ROOT / "data/raw/financials")
    ap.add_argument("--corporate-actions", type=Path,
                    default=ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv")
    ap.add_argument("--overrides", type=Path,
                    default=ROOT / "data/processed/manual_band_overrides.csv",
                    help="§6.5.7.4 人工覆盖表；列内的行直接落带，且不再叠加预告")
    ap.add_argument("--pool", type=Path, default=ROOT / "data/processed/a_share_core_valuation_pool.csv",
                    help="只用于按 总市值÷现价 交叉校验股本；缺失则跳过校验")
    ap.add_argument("--out", type=Path, default=None, help="缺省原地覆盖 --bands")
    args = ap.parse_args()

    with args.bands.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows, header = list(reader), list(reader.fieldnames or [])
    if not rows:
        print("生产带文件为空，未做任何叠加", file=sys.stderr)
        return 1

    forecasts: dict[str, dict] = {}
    if args.forecasts.exists():
        with args.forecasts.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                # 004 = 归属于上市公司股东的净利润，与模型的 parent_netprofit 同口径
                if row.get("predict_finance_code") == "004" and row.get("is_latest") == "T":
                    forecasts[(row.get("security_code") or "").strip()] = row

    express: dict[str, dict] = {}
    if args.disclosures.exists():
        with args.disclosures.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("disclosure_type") == "express_report":
                    code = (row.get("security_code") or "").strip()
                    prev = express.get(code)
                    if prev is None or (row.get("report_date") or "") > (prev.get("report_date") or ""):
                        express[code] = row

    actions: dict[str, list[dict]] = {}
    if args.corporate_actions.exists():
        with args.corporate_actions.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                actions.setdefault((row.get("security_code") or "").strip(), []).append(row)

    # §6.5.7.4 人工覆盖必须**同时落到生产带文件**，否则只改了展示层：
    # 扫描器的 `P/V` 读的是本文件，档案/池改了而这里没改，两层就会给出相反结论。
    # 判例：宏桥控股 2026-08-18 人工覆盖到 27.15-33.18（低估 +57%），
    # 而生产带仍是 0.1993，扫描器算出 `P/V` 96.3 并把它排除在合格集之外。
    overrides: dict[str, dict] = {}
    if args.overrides.exists():
        with args.overrides.open(encoding="utf-8-sig", newline="") as handle:
            overrides = {(r.get("security_code") or "").strip(): r for r in csv.DictReader(handle)}

    financials = load_financials(args.financials_dir)

    # 总股本交叉校验源：`total_market_cap_bn` 的单位是**十亿元**（宁德时代 1850.569 → 1.85 万亿），
    # 不是亿元——错读会让股本差 10 倍。
    market_shares: dict[str, float] = {}
    if args.pool.exists():
        with args.pool.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                cap, price = num(row.get("total_market_cap_bn")), num(row.get("valuation_price"))
                if cap and price and price > 0:
                    market_shares[(row.get("security_code") or "").strip()] = cap * 1e9 / price

    out_header = header + [c for c in OVERLAY_COLS if c not in header]
    applied, skipped, unchanged = [], [], 0
    bank_cleared: list[tuple[str, str, str]] = []
    override_applied: list[tuple[str, str, float, float]] = []

    for band in rows:
        for col in OVERLAY_COLS:
            band.setdefault(col, "")
        code = (band.get("security_code") or "").strip()
        name = band.get("security_name") or code
        band_period = (band.get("report_date") or "")[:10]
        if (band.get("status") or "").strip() not in ("", "ok"):
            unchanged += 1
            continue

        ovr = overrides.get(code)
        if ovr:
            lo, hi = num(ovr.get("band_low")), num(ovr.get("band_high"))
            if lo and hi and lo > 0:
                mid = (lo + hi) / 2
                band.update({
                    "pre_overlay_iv": band.get("intrinsic_value", ""),
                    "pre_overlay_report_date": band_period,
                    "forecast_overlay": "manual_override",
                    "forecast_notice_date": ovr.get("reviewed_at", ""),
                    "forecast_source": f"§6.5.7.4 人工覆盖（{ovr.get('reason_code')}）",
                    "bps_scale": "", "forecast_profit_yi": "",
                    "overlay_note": (f"人工覆盖，**不叠加预告**：{ovr.get('note')}"
                                     f"｜失效条件：{ovr.get('expires_when')}"),
                    "intrinsic_value": f"{mid:.4f}",
                    "band_low": f"{lo:.4f}", "band_high": f"{hi:.4f}",
                    "available_at": ovr.get("reviewed_at", ""),
                })
                override_applied.append((name, ovr.get("reviewed_at", ""), lo, hi))
                continue

        ev = pick_evidence(code, forecasts, express, band_period, args.as_of)
        if ev is None:
            unchanged += 1
            continue
        if band.get("forecast_overlay") and band.get("forecast_notice_date") == ev["notice_date"]:
            unchanged += 1  # 幂等：同一份证据不重复叠加
            continue

        path = (band.get("roic_path") or "").strip()
        if path == "bank_divspread":
            # 银行走 `V = 近12月每股分红 ÷ (十年国债+2%)`，**分子是分红不是利润**，
            # 故利润类证据（预告/快报）对带的影响恒为 0。按 §7.4「带变动不超过 2% 时只刷新证据日」，
            # 这里只推进证据日期、不动带值——否则该行会因利润公告永远挂在 `review_pending` 上，
            # 而它需要的复核其实是 §7.2 质量侧，不是估值侧。分红本身每次 §6.7 重建时由
            # `rebuild_bank_bands.py` 自动吸收，无需人工。
            band.update({
                "forecast_overlay": "bank_no_change",
                "forecast_notice_date": ev["notice_date"],
                "forecast_report_date": ev["report_date"],
                "forecast_profit_yi": f"{ev['profit'] / 1e8:.2f}",
                "forecast_source": ev["label"],
                "pre_overlay_iv": band.get("intrinsic_value", ""),
                "pre_overlay_report_date": band_period,
                "bps_scale": "1.000000",
                "overlay_note": (
                    f"§6.3 第 5 条：{ev['label']}（{ev['notice_date']}）归母 {ev['profit']/1e8:.2f} 亿，"
                    f"**带值不变**——本行走股利折现（分子为近 12 个月每股分红），利润类证据不进分子。"
                    f"按 §7.4 只推进证据日期以解除估值侧冻结；分红变动由 `rebuild_bank_bands.py` 每次重建自动吸收。"
                    f"质量侧复核（§7.2）不受本条影响。"),
                "report_date": ev["report_date"],
                "available_at": ev["notice_date"],
                "notice_date": ev["notice_date"],
            })
            bank_cleared.append((name, ev["label"], ev["notice_date"]))
            continue
        if path not in ("growth", "zero_growth", "equity_fallback"):
            skipped.append((name, f"估值路径 {path or '未知'} 不适用：该路径的带不由盈利输入线性决定，bps 通道不适用"))
            continue

        periods = financials.get(code, {})
        base_row = periods.get(band_period)
        bps = num(band.get("bps"))
        if base_row is None or bps is None or bps <= 0:
            skipped.append((name, f"缺基线：报告期 {band_period} 的财务行或 bps 不可得"))
            continue
        base_profit = num(base_row.get("parent_netprofit"))
        if base_profit is None:
            skipped.append((name, f"基线 {band_period} 无归母净利"))
            continue

        shares, shares_src = derive_shares(periods, band_period, market_shares.get(code))
        if shares is None:
            skipped.append((name, f"股本不可用：{shares_src}"))
            continue

        # 累计口径对齐——**只有两种基线算得出区间利润**：
        #   ① 同一会计年度的更早一期：两边都是本年累计数，作差即区间利润；
        #   ② 上一会计年度的年报：新年度从零起算，预告本身就是区间利润。
        # 其它基线（如上年三季报对本年半年报）会漏掉中间若干季度的留存收益，
        # **算出来的不是区间利润**。这类必须跳过而不是硬算——判例：京东方A 的生产带
        # 停在 2023-09-30，与 2026-06-30 预告之间隔着近三年利润，硬算会把带推错。
        same_year = band_period[:4] == ev["report_date"][:4]
        prior_year_end = (band_period.endswith("-12-31")
                          and int(band_period[:4]) + 1 == int(ev["report_date"][:4]))
        if same_year and band_period >= ev["report_date"]:
            skipped.append((name, f"基线 {band_period} 不早于预告期 {ev['report_date']}，无法作差"))
            continue
        if not same_year and not prior_year_end:
            skipped.append((name, f"基线 {band_period} 与预告期 {ev['report_date']} 累计口径对不齐"
                                  f"（既非同年更早期，也非上年年报），区间利润算不出"))
            continue
        delta_profit = ev["profit"] - base_profit if same_year else ev["profit"]
        dps = dividends_between(actions.get(code, []), band_period, ev["report_date"])
        delta_bps = delta_profit / shares - dps
        new_bps = bps + delta_bps
        if new_bps <= 0:
            skipped.append((name, f"叠加后每股净资产 {new_bps:.4f} ≤ 0，模型不可估，须走 §6.5.7.4 逐票建档"))
            continue
        scale = new_bps / bps

        res = recompute(band, scale)
        if res is None:
            skipped.append((name, f"重算失败（路径 {path}，输入不全）"))
            continue
        ev_new, iv_new, scaled_field = res
        if iv_new <= 0:
            skipped.append((name, f"叠加后股权价值 {iv_new:.2f} ≤ 0：净负债超过企业价值"))
            continue

        old_iv = num(band.get("intrinsic_value"))
        direction = "偏高" if delta_profit < 0 else "偏低"
        band.update({
            "pre_overlay_iv": f"{old_iv:.4f}" if old_iv is not None else "",
            "pre_overlay_report_date": band_period,
            "forecast_overlay": ev["kind"],
            "forecast_notice_date": ev["notice_date"],
            "forecast_report_date": ev["report_date"],
            "forecast_profit_yi": f"{ev['profit'] / 1e8:.2f}",
            "forecast_source": ev["label"],
            "bps_scale": f"{scale:.6f}",
            "overlay_note": (
                f"§6.3 第 5 条叠加：{ev['label']}（{ev['notice_date']}）归母 {ev['profit']/1e8:.2f} 亿，"
                f"基线 {band_period} 累计 {base_profit/1e8:.2f} 亿 → 区间利润 {delta_profit/1e8:.2f} 亿；"
                f"股本 {shares/1e8:.2f} 亿股（源 {shares_src}）、期间每股分红 {dps:.4f} 元 → "
                f"每股净资产 {bps:.4f} → {new_bps:.4f}（×{scale:.4f}）；"
                f"归一化锚（{'roe0' if path == 'equity_fallback' else 'ratio0'}）不动。"
                f"**net_debt_ps 未调整**（预告无资产负债表），"
                f"该省略使本行的带{direction}。正式报告披露后由 §6.7 机械带取代。"),
            "report_date": ev["report_date"],
            "available_at": ev["notice_date"],
            "notice_date": ev["notice_date"],
            "intrinsic_value": f"{iv_new:.4f}",
            "band_low": f"{BAND_LOW_COEF * iv_new:.4f}",
            "band_high": f"{BAND_HIGH_COEF * iv_new:.4f}",
        })
        if ev_new is not None:
            band["ev_ps"] = f"{ev_new:.4f}"
        scaled_now = num(band.get(scaled_field))
        if scaled_now is not None:
            band[scaled_field] = f"{scaled_now * scale:.4f}"
        band["bps"] = f"{new_bps:.4f}"
        applied.append((name, old_iv, iv_new, ev["label"], ev["notice_date"], delta_profit / 1e8))

    out_path = args.out or args.bands
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=out_header)
        writer.writeheader()
        writer.writerows(rows)

    print(f"预告／快报叠加（§6.3 第 5 条）as-of {args.as_of} → {out_path.name}")
    print(f"  已叠加 {len(applied)} 只｜人工覆盖 {len(override_applied)} 只｜"
          f"银行只推证据日 {len(bank_cleared)} 只｜跳过 {len(skipped)} 只｜无证据或已叠加 {unchanged} 只")
    if applied:
        applied.sort(key=lambda a: (a[2] / a[1] - 1) if a[1] else 0)
        print(f"  {'名称':<10}{'原 IV':>10}{'新 IV':>10}{'变动':>9}  {'区间利润(亿)':>12}  证据")
        for name, old, new, label, notice, dprofit in applied:
            chg = f"{new / old - 1:+.1%}" if old else "—"
            print(f"  {name:<10}{old or 0:>10.2f}{new:>10.2f}{chg:>9}  {dprofit:>12.2f}  {label} {notice}")
    for name, when, lo, hi in override_applied:
        print(f"  · §6.5.7.4 人工覆盖落生产带：{name} → {lo:.2f}-{hi:.2f}（{when}）")
    for name, label, notice in bank_cleared:
        print(f"  · 银行只推进证据日、带值不变：{name}（{label} {notice}）")
    for name, why in skipped:
        print(f"  ⚠ 跳过 {name}：{why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
