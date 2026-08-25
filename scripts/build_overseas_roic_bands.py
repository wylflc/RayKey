#!/usr/bin/env python3
"""海外关注清单（§6.8）按 A 股现行 ROIC 口径（§6.5.2.3）重算合理估值，写回 `overseas_watchlist_valuation.csv`。

与 `build_historical_valuation_bands.py --value-model roic`（生产参数：conditional3／hybrid／peak 守卫）逐项同式：
  history = 最近 5 个财年（至少 3 年）；ROIC0 = 归一化 ROIC；增量 ROIC（端点）；再投资率；
  rd = 历史利息/有息负债（夹 2%~12%，缺省 4.5%）；税率 = 最新报告口径观测；WACC 账面权重；
  **每股 NOPAT 锚（v4.47，OI-082 海外先行）**：各年 NOPAT ÷ **最新稀释股数**（送转/拆股自动消除、回购缩股不进历史），
  增长态（近 3 年严格上升）取最新、否则取近 3 年中位；周期守卫比较 **NOPAT/(母公司权益＋累计回购)** 的最新值 vs 10 年中位
  （> 1.6× → 周期峰 → 取 5 年中位每股 NOPAT）——回购造成的权益缩水不再被读成周期峰（A 股引擎仍用 NOPAT/权益×BPS，待 §12.1 A/B）；
  g0 = max(min(增量ROIC,40%)×再投资率, NOPAT 3 年 CAGR) 夹 [0,25%]；ROIC_T = min(WACC + 档位终值超额, ROIC0)；
  g_T = min(3%, 无风险利率)；fade 10 年；每股价值 = intrinsic_value(NOPAT/股) − 净负债/股；带 = V × [0.90, 1.10]。
差别（成文于此，不藏在代码里）：
  * r = rf + β×ERP 中 rf 取美债 10Y（美元 ADR 与联系汇率港股同用），ERP 按**经营地**取 Damodaran 国家 ERP
    （`data/reference/overseas_valuation_inputs.csv`），β 按质量档与 A 股同表（L1 0.9／L2 1.0／L3、L4 1.3）；
  * 报表货币 ≠ 交易货币时按同文件汇率折算，ADR 按每 ADR 普通股数折算；
  * 金融企业（伯克希尔）ROIC 不适用，沿用档案带并标明；韩股无三表源、SpaceX 无申报 → 无法估值；
  * ROIC 路径被拒（NOPAT 非正、终值 ROIC 距 g_T 不足、净负债超过企业价值等）→ 无法估值，原因写入 `band_derivation_text`，
    旧档案带只作参考文本保留（与 A 股「没算完的带一律判无法估值」同规）。
用法：
  python3 scripts/build_overseas_roic_bands.py --check                 # 只算不写
  python3 scripts/build_overseas_roic_bands.py --as-of YYYY-MM-DD [--quotes fetch|skip]
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import roic_inputs  # noqa: E402
from intrinsic_value import (ValuationError, cost_of_equity, intrinsic_value,  # noqa: E402
                             terminal_growth_ceiling, DEFAULT_G_TERMINAL)
from build_a_share_core_valuation_pool import effective_valuation_tier  # noqa: E402

WATCHLIST = ROOT / "data/processed/overseas_watchlist_valuation.csv"
YEARS_CSV = ROOT / "data/interim/overseas_roic_years.csv"
INPUTS_CSV = ROOT / "data/reference/overseas_valuation_inputs.csv"
REPORT_EVIDENCE = ROOT / "data/reference/overseas_report_evidence.csv"
BAND_LOW_COEF, BAND_HIGH_COEF = 0.90, 1.10
BETA_BY_TIER = {"L1": 0.9, "L2": 1.0, "L3": 1.3, "L4": 1.3}
TERMINAL_EXCESS_BY_TIER = {"L1": 0.06, "L2": 0.03, "L3": 0.0, "L4": 0.0}
ROE_YEARS, MIN_YEARS, IROE_CAP, G0_CAP, G0_FLOOR = 5, 3, 0.40, 0.25, 0.0
N_FADE, N1, MIN_TERMINAL_SPREAD, PEAK_K, TRAIL_WEIGHT = 10, 0, 0.02, 1.6, 1.0
# 经营地 ERP 键、交易货币、每 ADR/港股对应普通股数、报表币→交易币汇率键
COMPANY_CFG = {
    # US 上市
    "TSM": dict(erp="erp_tw", ccy="USD", adr=5, fx="fx_usd_twd", fx_inv=True),
    "ASML": dict(erp="erp_nl", ccy="USD", adr=1, fx="fx_usd_eur", fx_inv=True),
    "PDD": dict(erp="erp_cn", ccy="USD", adr=4, fx="fx_usd_cny", fx_inv=True),
    # HK 上市（人民币报表 → 港币）
    "00700": dict(erp="erp_hk", ccy="HKD", adr=1, fx="fx_cny_hkd", fx_inv=False),
    "09992": dict(erp="erp_hk", ccy="HKD", adr=1, fx="fx_cny_hkd", fx_inv=False),
    "09618": dict(erp="erp_hk", ccy="HKD", adr=1, fx="fx_cny_hkd", fx_inv=False),
    "09988": dict(erp="erp_hk", ccy="HKD", adr=1, fx="fx_cny_hkd", fx_inv=False),
    "03690": dict(erp="erp_hk", ccy="HKD", adr=1, fx="fx_cny_hkd", fx_inv=False),
    "06862": dict(erp="erp_hk", ccy="HKD", adr=1, fx="fx_cny_hkd", fx_inv=False),
    "03888": dict(erp="erp_hk", ccy="HKD", adr=1, fx="fx_cny_hkd", fx_inv=False),
}
FINANCIAL_KEEP = {"BRK.B": "金融资本型（保险浮存金＋控股）：ROIC 口径的投入资本/NOPAT 对金融企业不可定义，与 A 股「金融企业退回权益口径」同规；沿用档案 §6.5.2 J 隐含 PB 带，不按 ROIC 重算"}
NO_SOURCE = {"005930": "韩股无免密钥三表取数源（东财 HK F10／SEC 均不覆盖），ROIC 口径不可算",
             "000660": "韩股无免密钥三表取数源（东财 HK F10／SEC 均不覆盖），ROIC 口径不可算",
             "SPCX": "无 SEC 申报（无 CIK），三表不可得"}


def _f(v):
    try:
        return float(v) if v not in (None, "", "—") else None
    except (TypeError, ValueError):
        return None


def load_inputs() -> dict[str, float]:
    return {r["key"]: float(r["value"]) for r in csv.DictReader(INPUTS_CSV.open(encoding="utf-8"))}


def load_years() -> dict[str, list[roic_inputs.RoicYear]]:
    out: dict[str, list[roic_inputs.RoicYear]] = {}
    meta: dict[str, dict] = {}
    current: dict[str, roic_inputs.RoicYear] = {}
    current_meta: dict[str, dict] = {}
    for r in csv.DictReader(YEARS_CSV.open(encoding="utf-8")):
        y = roic_inputs.RoicYear(period=r["period"], notice_date=r["notice_date"])
        y.revenue, y.ebit, y.nopat = _f(r["revenue"]), _f(r["ebit"]), _f(r["nopat"])
        y.tax_rate = _f(r["tax_rate"]); y.tax_rate_observed = r["tax_rate_observed"] == "1"
        y.total_equity, y.parent_equity = _f(r["total_equity"]), _f(r["parent_equity"])
        y.minority_equity = _f(r["minority_equity"]) or 0.0
        y.interest_debt, y.excess_cash = _f(r["interest_debt"]) or 0.0, _f(r["excess_cash"]) or 0.0
        y.invested_capital = _f(r["invested_capital"])
        y.capex, y.dep_amort, y.cfo = _f(r["capex"]) or 0.0, _f(r["dep_amort"]) or 0.0, _f(r["cfo"])
        y.interest_expense = _f(r["interest_expense"]) or 0.0
        y.shares = _f(r["shares"])  # type: ignore[attr-defined]
        y.buybacks = _f(r.get("buybacks")) or 0.0  # type: ignore[attr-defined]
        y.dividends_paid = _f(r.get("dividends_paid")) or 0.0  # type: ignore[attr-defined]
        row_meta = {"ccy": r["report_currency"], "source": r["source"], "tags": r["tags_used"],
                    "report_label": r.get("report_label", ""), "evidence_url": r.get("evidence_url", "")}
        if r.get("period_type") == "ttm":
            current[r["security_code"]] = y
            current_meta[r["security_code"]] = row_meta
        else:
            out.setdefault(r["security_code"], []).append(y)
            meta[r["security_code"]] = row_meta
    for code in out:
        out[code].sort(key=lambda y: y.period)
    load_years.meta = meta  # type: ignore[attr-defined]
    load_years.current = current  # type: ignore[attr-defined]
    load_years.current_meta = current_meta  # type: ignore[attr-defined]
    return out


def load_report_evidence(as_of: str) -> dict[str, dict[str, str]]:
    if not REPORT_EVIDENCE.exists():
        return {}
    return {r["security_code"]: r for r in csv.DictReader(REPORT_EVIDENCE.open(encoding="utf-8-sig"))
            if r.get("evidence_date", "") <= as_of}


def value_company(code: str, tier: str, years: list[roic_inputs.RoicYear], inp: dict[str, float],
                  current: roic_inputs.RoicYear | None = None) -> dict:
    """复刻 ROIC 路径，返回 {status, value_report_ccy, path, text, ...}。"""
    res: dict = {"status": "rejected", "reason": "", "path": "", "text": ""}
    cfg = COMPANY_CFG.get(code, dict(erp="erp_us", ccy="USD", adr=1, fx=None, fx_inv=False))
    history = years[-ROE_YEARS:]
    if len(history) < MIN_YEARS:
        res["reason"] = f"三大报表年份仅 {len(history)} < 要求 {MIN_YEARS} 年"; return res
    annual_latest = history[-1]
    latest = current if current and current.period > annual_latest.period else annual_latest
    rf, erp = inp["rf_usd"], inp[cfg["erp"]]
    beta = BETA_BY_TIER.get(tier, 1.0)
    r = cost_of_equity(rf, erp, beta)
    g_terminal = min(DEFAULT_G_TERMINAL, terminal_growth_ceiling(rf))
    excess_t = TERMINAL_EXCESS_BY_TIER.get(tier, 0.0)
    roic0 = roic_inputs.normalized_roic(history)
    iroic = roic_inputs.incremental_roic(history)
    rr = roic_inputs.reinvestment_rate(history)
    rd = roic_inputs.cost_of_debt(history)
    tax = latest.tax_rate if latest.tax_rate is not None else 0.25
    w = roic_inputs.wacc(r, rd, tax, latest.total_equity or 0.0, latest.interest_debt)
    shares = getattr(latest, "shares", None)
    if not shares or shares <= 0:
        res["reason"] = "股数不可得（无稀释加权股数/期末股数标签）"; return res
    if latest.parent_equity is None or latest.parent_equity <= 0:
        res["reason"] = "母公司权益非正，股数法无法折每股"; return res
    if latest.nopat is None or latest.nopat <= 0:
        res["reason"] = f"最新报告口径 NOPAT={latest.nopat/1e9:.2f}b ≤ 0：息税前利润非正，按现金折现无意义（A 股同规，按 §6.5.2.4 判无法估值）"; return res
    # ---- OI-082（v4.47，海外先行）：每股 NOPAT 锚 = 各年 NOPAT ÷ 最新稀释股数；周期守卫用回购回加后的权益比率
    # 最新正式季报另以 TTM 作为最末观察点；年度历史仍只用于 ROIC0/增量 ROIC/再投资率，避免把重叠 TTM 当第六个财年。
    long_hist = years[-10:]
    cum = 0.0
    adj_ratio_by_period: dict[str, float] = {}
    for y in long_hist:                      # 累计回购自 10 年窗首年起回加，逐年恢复被回购削掉的权益基数
        cum += getattr(y, "buybacks", 0.0) or 0.0
        if y.nopat is not None and y.parent_equity is not None and (y.parent_equity + cum) > 0:
            adj_ratio_by_period[y.period] = y.nopat / (y.parent_equity + cum)
    long_ratios = [adj_ratio_by_period[y.period] for y in long_hist if y.period in adj_ratio_by_period]
    if latest is not annual_latest and latest.nopat is not None and latest.parent_equity is not None and latest.parent_equity + cum > 0:
        long_ratios.append(latest.nopat / (latest.parent_equity + cum))
    nopat_cyclical = (len(long_ratios) >= 4 and long_ratios[-1] > 0 and long_ratios[-1] > PEAK_K * statistics.median(long_ratios))
    nps = [y.nopat / shares for y in history if y.nopat is not None]
    if latest is not annual_latest and latest.nopat is not None:
        nps.append(latest.nopat / shares)
    if not nps:
        res["reason"] = "无可用的每股 NOPAT"; return res
    if nopat_cyclical:
        nopat_ps, mode = statistics.median(nps[-5:]), "cyclical_median"
    elif len(nps) >= 3 and nps[-1] > nps[-2] > nps[-3]:
        nopat_ps, mode = nps[-1], "ttm_growth"
    elif len(nps) >= 3:
        nopat_ps, mode = statistics.median(nps[-3:]), "median3"
    else:
        nopat_ps, mode = statistics.median(nps), "median"
    ratio0 = nopat_ps / (latest.parent_equity / shares) if latest.parent_equity else float("nan")
    bps = latest.parent_equity / shares
    cum_buyback_latest = cum
    net_debt_ps = (latest.interest_debt - latest.excess_cash + latest.minority_equity) / shares
    if nopat_ps <= 0:
        res["reason"] = "正常化每股 NOPAT 非正"; return res
    v_zero = nopat_ps / w - net_debt_ps
    roic_ok = roic0 is not None and roic0 > g_terminal + MIN_TERMINAL_SPREAD
    common = dict(r=r, rf=rf, erp=erp, beta=beta, rd=rd, tax=tax, wacc=w, roic0=roic0, iroic=iroic, rr=rr,
                  ratio0=ratio0, mode=mode, nopat_ps=nopat_ps, net_debt_ps=net_debt_ps, bps=bps, shares=shares,
                  g_terminal=g_terminal, cyclical=nopat_cyclical, years=[y.period[:4] for y in history], v_zero=v_zero,
                  nps=nps, adj_ratio_latest=(long_ratios[-1] if long_ratios else None),
                  adj_ratio_median=(statistics.median(long_ratios) if long_ratios else None),
                  cum_buybacks=cum_buyback_latest, buyback_latest=getattr(latest, "buybacks", 0.0) or 0.0,
                  current_period=(latest.period if latest is not annual_latest else ""))
    if not roic_ok:
        if v_zero <= 0:
            res["reason"] = f"零增长股权价值 {v_zero:.2f} ≤ 0：净负债超过零增长企业价值"; res.update(common); return res
        res.update(common, status="ok", path="zero_growth", value=v_zero, g0=0.0, roic_t=None, terminal_share=1.0)
        return res
    g_capital = min(iroic, IROE_CAP) * min(rr, 1.0) if (rr is not None and iroic is not None and iroic > 0 and rr > 0) else None
    g_trail = None
    if not nopat_cyclical:
        cagr = roic_inputs.trailing_nopat_cagr(history)
        if cagr is not None and cagr > 0:
            g_trail = cagr * TRAIL_WEIGHT
    cands = [g for g in (g_capital, g_trail) if g is not None]
    g0 = max(min(max(cands) if cands else 0.0, G0_CAP), G0_FLOOR)
    g_src = ("trailing" if g_trail is not None and (g_capital is None or g_trail >= g_capital) else "capital" if g_capital is not None else "none")
    roic_t = min(w + excess_t, roic0)
    if roic_t <= g_terminal + MIN_TERMINAL_SPREAD:
        res["reason"] = f"终值 ROIC={roic_t:.2%} 距 g_T={g_terminal:.2%} 不足 {MIN_TERMINAL_SPREAD:.1%}"; res.update(common); return res
    try:
        iv = intrinsic_value(nopat_ps, roic0, g0, w, roe_terminal=roic_t, g_terminal=g_terminal, n=N_FADE, n1=N1)
    except ValuationError as exc:
        res["reason"] = str(exc); res.update(common); return res
    value = iv.intrinsic_value - net_debt_ps
    if value <= 0:
        res["reason"] = f"股权价值 {value:.2f} ≤ 0：净负债 {net_debt_ps:.2f} 超过企业价值 {iv.intrinsic_value:.2f}"; res.update(common); return res
    res.update(common, status="ok", path="growth", value=value, g0=g0, g_src=g_src, g_capital=g_capital, g_trail=g_trail,
               roic_t=roic_t, terminal_share=iv.terminal_share, ev_ps=iv.intrinsic_value)
    return res


def derivation_text(code: str, r: dict, meta: dict, cfg: dict, fx: float, value_trade: float | None, ccy_report: str) -> str:
    if r["status"] != "ok":
        base = f"ROIC 口径（§6.5.2.3，与 A 股生产参数同式）不可算：{r['reason']}"
        if r.get("wacc"):
            base += f"；已算到 WACC {r['wacc']:.2%}（r={r['r']:.2%}=rf {r['rf']:.2%}+β{r['beta']}×ERP {r['erp']:.2%}，rd {r['rd']:.2%}，t {r['tax']:.0%}）"
        return base
    g_line = ("零增长：V = NOPAT/股 ÷ WACC − 净负债/股" if r["path"] == "zero_growth" else
              f"增长 g0={r['g0']:.1%}（来源 {r['g_src']}：资本腿 {('%.1f%%' % (r['g_capital']*100)) if r.get('g_capital') is not None else '—'}=min(增量ROIC {('%.1f%%' % (r['iroic']*100)) if r['iroic'] is not None else '—'},40%)×再投资率 {('%.0f%%' % (r['rr']*100)) if r['rr'] is not None else '—'}，增速腿 {('%.1f%%' % (r['g_trail']*100)) if r.get('g_trail') is not None else '—'}），ROIC_T=min(WACC+档位超额, ROIC0)={r['roic_t']:.1%}，g_T={r['g_terminal']:.1%}，fade {N_FADE} 年，终值占比 {r['terminal_share']:.0%}")
    fx_line = (f"；报表币 {ccy_report} → 交易币 {cfg['ccy']} 汇率 {fx:.4f}" + (f"，每 ADR {cfg['adr']} 股" if cfg['adr'] != 1 else "")) if (ccy_report != cfg["ccy"] or cfg["adr"] != 1) else ""
    nps_txt = "／".join(f"{v:.2f}" for v in r["nps"])
    guard_txt = (f"周期守卫 NOPAT/(权益＋累计回购 {r['cum_buybacks']/1e9:.1f}b)：最新 {r['adj_ratio_latest']:.3f} vs 10 年中位 {r['adj_ratio_median']:.3f}"
                 f"（{'命中→取 5 年中位' if r['cyclical'] else '未命中'}）" if r.get("adj_ratio_latest") is not None else "周期守卫：无可比比率")
    period_text = (f"财年 {r['years'][0]}~{r['years'][-1]}＋截至 {r['current_period']} TTM"
                   if r.get("current_period") else f"财年 {r['years'][0]}~{r['years'][-1]}")
    return (f"ROIC·{'增长' if r['path']=='growth' else '零增长'}（§6.5.2.3 同口径，{period_text}，{meta.get('source','')}）："
            f"每股 NOPAT 锚（v4.47 OI-082：各年 NOPAT ÷ 最新稀释股数 {r['shares']/1e6:,.0f}m）序列 {nps_txt} → 取 **{r['nopat_ps']:.3f}**（{r['mode']}）；{guard_txt}；"
            f"最新观察点回购 {r['buyback_latest']/1e9:.1f}b；BPS {r['bps']:.2f}；"
            f"ROIC0 {r['roic0']:.1%}；WACC {r['wacc']:.2%}（r {r['r']:.2%} = rf {r['rf']:.2%} + β{r['beta']}×ERP {r['erp']:.2%}；rd {r['rd']:.2%}；t {r['tax']:.0%}；账面权重）；{g_line}；"
            f"净负债/股 {r['net_debt_ps']:.3f}（有息负债−超额现金＋少数股东权益）；**V = {r['value']:.3f} {ccy_report}/普通股**{fx_line}"
            + (f" → **{value_trade:,.2f} {cfg['ccy']}**" if value_trade else "") + f"；带 = V×[0.90,1.10]。标签：{meta.get('tags','')[:400]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--quotes", choices=("fetch", "skip"), default="fetch")
    args = ap.parse_args()
    inp = load_inputs()
    years = load_years(); meta = load_years.meta  # type: ignore[attr-defined]
    current = load_years.current  # type: ignore[attr-defined]
    current_meta = load_years.current_meta  # type: ignore[attr-defined]
    evidence = load_report_evidence(args.as_of)
    rows = list(csv.DictReader(WATCHLIST.open(encoding="utf-8-sig")))
    quotes = {}
    if args.quotes == "fetch" and not args.check:
        try:
            from overseas_quotes import fetch_overseas_quotes
            quotes = fetch_overseas_quotes([(r["market_type"], r["security_code"]) for r in rows])
        except Exception as exc:  # noqa: BLE001
            print(f"⚠ 行情取数失败，沿用复核时点价：{exc}")
    print(f"{'代码':<8}{'名称':<14}{'档':<4}{'状态':<12}{'V(报表币)':>12}{'V(交易币)':>12}{'现价':>10}{'P/V':>7}  说明")
    changed = 0
    evidence_changed = 0
    for row in rows:
        code, name, tier = row["security_code"], row["security_name"], str(row.get("quality_tier", "L2"))
        report = evidence.get(code) or {}
        evidence_date = report.get("evidence_date") or row.get("evidence_available_at") or ""
        evidence_event = report.get("report_event") or row.get("valuation_evidence_event") or ""
        cfg = COMPANY_CFG.get(code, dict(erp="erp_us", ccy=row.get("currency") or "USD", adr=1, fx=None, fx_inv=False))
        q = quotes.get(f"{row['market_type'].upper()}:{code}") or {}
        price = _f(q.get("price")) or _f(row.get("valuation_price"))
        price_as_of = (str(q.get("quote_time") or "")[:10] if q else row.get("valuation_price_as_of")) or row.get("valuation_price_as_of")
        old_band = f"{row.get('fair_price_low')}~{row.get('fair_price_high')}（{row.get('band_method','')[:40]}）"
        if code in FINANCIAL_KEEP:
            method, text, lo, hi = "隐含PB（金融资本型，ROIC 不适用）", FINANCIAL_KEEP[code] + f"；沿用带 {old_band}。", _f(row.get("fair_price_low")), _f(row.get("fair_price_high"))
            v_trade = (lo + hi) / 2 if lo and hi else None
            status = "keep"
        elif code in NO_SOURCE or code not in years:
            method, text, lo, hi, v_trade, status = "无法估值", f"{NO_SOURCE.get(code, '无三表数据')}；旧档案带 {old_band} 仅供参考，不再作为合理估值。", None, None, None, "unavailable"
        else:
            model_current = current.get(code)
            r = value_company(code, tier, years[code], inp, model_current)
            model_meta = current_meta.get(code, meta[code]) if model_current else meta[code]
            ccy_report = model_meta["ccy"]
            fx = 1.0
            if cfg.get("fx"):
                fx = inp[cfg["fx"]]
                fx = (1.0 / fx) if cfg.get("fx_inv") else fx
            if r["status"] == "ok":
                v_trade = r["value"] * fx * cfg["adr"]
                lo, hi = BAND_LOW_COEF * v_trade, BAND_HIGH_COEF * v_trade
                method = f"ROIC·{'增长' if r['path']=='growth' else '零增长'}（§6.5.2.3 同口径）"
                status = "ok"
            else:
                v_trade, lo, hi, method, status = None, None, None, "无法估值", "rejected"
            text = derivation_text(code, r, model_meta, cfg, fx, v_trade, ccy_report)
            if status == "rejected":
                text += f"；旧档案带 {old_band} 仅供参考，不再作为合理估值。"
        pv = (price / v_trade) if (price and v_trade) else None
        tier_new = "无法估值" if v_trade is None else (effective_valuation_tier(price, lo, hi) or row.get("valuation_tier", ""))
        print(f"{code:<8}{name:<14}{tier:<4}{status:<12}{(f'{r['value']:.2f}' if status in ('ok',) else '—'):>12}{(f'{v_trade:,.2f}' if v_trade else '—'):>12}{(f'{price:,.2f}' if price else '—'):>10}{(f'{pv:.3f}' if pv else '—'):>7}  {method}{'' if status=='ok' else '：' + text[:90]}")
        if args.check:
            continue
        before = (row.get("fair_price_low", ""), row.get("fair_price_high", ""), row.get("band_method", ""))
        row["fair_price_low"] = "" if lo is None else (f"{lo:.0f}" if cfg["ccy"] == "KRW" else f"{lo:.2f}")
        row["fair_price_high"] = "" if hi is None else (f"{hi:.0f}" if cfg["ccy"] == "KRW" else f"{hi:.2f}")
        row["valuation_method"] = method
        row["band_method"] = method
        row["band_derivation"] = "roic" if status == "ok" else ("dossier" if status == "keep" else "unvaluable")
        row["band_derivation_text"] = text
        row["fair_price_basis"] = text
        row["valuation_tier"] = tier_new
        if price:
            row["valuation_price"] = f"{price:.2f}" if cfg["ccy"] != "KRW" else f"{price:.0f}"
            row["valuation_price_as_of"] = price_as_of or args.as_of
        row["valuation_reason"] = (str(row.get("valuation_reason", "")).split("｜**本次定档")[0]
                                   + f"｜**本次定档（{evidence_date or '证据日缺失'}，{evidence_event or '定期报告'}，ROIC 口径）**：{method}；带 "
                                   + ("—" if lo is None else f"{lo:,.2f}~{hi:,.2f}") + f"；复核时点价 {row.get('valuation_price') or 'NA'}（{row.get('valuation_price_as_of') or 'NA'}）→ **{tier_new}**。")
        before_evidence = (row.get("valuation_reviewed_at", ""), row.get("valuation_evidence_event", ""),
                           row.get("evidence_available_at", ""), row.get("last_report_date", ""))
        if evidence_date:
            # OI-102：展示日期回答“本次估值依据何时公开”，不得写脚本运行日。
            row["valuation_reviewed_at"] = evidence_date
            row["evidence_available_at"] = evidence_date
            row["last_report_date"] = evidence_date
        if evidence_event:
            row["valuation_evidence_event"] = evidence_event
        # 仅在正式证据已推进到预期窗口时清理预期日；单纯过期须留给待核验告警。
        next_report = row.get("next_report_date", "")
        if (next_report and evidence_date
                and (evidence_date[:7] == next_report[:7] or evidence_date >= next_report)):
            row["next_report_date"] = ""
            row["next_report_source"] = ""
        evidence_updated = ((row.get("valuation_reviewed_at", ""), row.get("valuation_evidence_event", ""),
                             row.get("evidence_available_at", ""), row.get("last_report_date", "")) != before_evidence)
        if evidence_updated:
            evidence_changed += 1
        row["dossier_status"] = "active" if status in ("ok", "keep") else "unvaluable_pending_input"
        band_changed = (row["fair_price_low"], row["fair_price_high"], row["band_method"]) != before
        if band_changed:
            changed += 1
        if evidence_updated or band_changed:
            row["valuation_batch_id"] = f"overseas_review_{args.as_of.replace('-', '')}"
    if args.check:
        return 0
    fields = list(rows[0].keys())
    with WATCHLIST.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    # 逐票 README 追加/替换「ROIC 口径估值」节
    for row in rows:
        d = ROOT / (row.get("dossier_dir") or f"data/companies/{row['security_code']}_{row['security_name']}")
        if not d.exists():
            continue
        readme = d / "README.md"
        body = readme.read_text(encoding="utf-8") if readme.exists() else f"# {row['security_name']}\n"
        marker = "## ROIC 口径估值（§6.5.2.3 同口径）"
        section = (f"{marker}\n\n证据 {row.get('valuation_reviewed_at') or '—'}（{row.get('valuation_evidence_event') or '—'}）。方法：{row['band_method']}；"
                   f"带 {row.get('fair_price_low') or '—'}~{row.get('fair_price_high') or '—'} {row.get('currency','')}；审定档 {row['valuation_tier']}。\n\n{row['band_derivation_text']}\n")
        if marker in body:
            head = body.split(marker)[0]
            body = head + section
        else:
            body = body.rstrip("\n") + "\n\n" + section
        readme.write_text(body, encoding="utf-8")
    print(f"\n写回 {WATCHLIST.name}：{changed} 行带/方法变化，{evidence_changed} 行证据日期/事件变化；README 已刷新 ROIC 节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
