#!/usr/bin/env python3
"""海外关注清单（§6.8）按 A 股现行 ROIC 口径（§6.5.2.3）重算合理估值，写回 `overseas_watchlist_valuation.csv`。

与 `build_historical_valuation_bands.py --value-model roic`（§6.7 第 2 步生产参数）逐项同式：
  history = 最近 5 个财年（至少 3 年）；ROIC0 = 归一化 ROIC；增量 ROIC（端点）；再投资率；
  rd = 历史利息/有息负债（夹 2%~12%，缺省 4.5%）；税率 = 最新报告口径观测；WACC 账面权重；
  **锚**：比率 = 各年 NOPAT ÷ 当年母公司权益，季报观察点的「当期」= 最新年报比率 × f（f = NOPAT TTM ÷ 最新年报 NOPAT），
  增长态信任度 λ = 近两次年度变动中上行次数 ÷ 2，非周期锚 = 三年中位 + λ×(当期 − 三年中位)；
  周期守卫坡道（OI-088／OI-090）：s = 当期比率 ÷ 十年中位，w = clip((s − 1.3)/0.6, 0, 1)，谷 v 同式取 1/s，
  ratio0 = (1−max(w,v))×非周期锚 + max(w,v)×五年中位；λ 与三年／五年／十年中位只取年报；每股 NOPAT 锚 = ratio0 × 当期 BPS；
  g0 = max(min(增量ROIC,40%)×再投资率, NOPAT 3 年 CAGR × W × (1−w) × d) 夹 [0,25%]，W = `TRAIL_WEIGHT` = 0（与 §6.7 第 2 步
  `--roic-trail-weight 0` 同），d = min(1, 最新年报/上年) × min(1, TTM/最新年报)；ROIC_T = min(WACC + 档位终值超额, ROIC0)；
  g_T = min(3%, 无风险利率)；fade 10 年；每股价值 = intrinsic_value(NOPAT/股) − 净负债/股；带 = V × [0.90, 1.10]。
差别（成文于此，不藏在代码里）：
  * r = rf + β×ERP 中 rf 取美债 10Y（美元 ADR 与联系汇率港股同用），ERP 按**经营地**取 Damodaran 国家 ERP
    （`data/reference/overseas_valuation_inputs.csv`），β 按质量档与 A 股同表（L1 0.9／L2 1.0／L3、L4 1.3）；
  * 报表货币 ≠ 交易货币时按同文件汇率折算，ADR 按每 ADR 普通股数折算；
  * 金融企业（伯克希尔）ROIC 不适用，沿用档案带并标明；韩股无三表源、SpaceX 无申报 → 无法估值；
  * 经营账面 E_op 取母公司权益（海外三表无外生权益／未花募资／注销识别）；季报当期的 f 取 NOPAT TTM ÷ 年报 NOPAT（A 股用归母净利 TTM 因子）；
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

WATCHLIST = ROOT / "data/processed/overseas_watchlist_valuation.csv"
YEARS_CSV = ROOT / "data/interim/overseas_roic_years.csv"
INPUTS_CSV = ROOT / "data/reference/overseas_valuation_inputs.csv"
REPORT_EVIDENCE = ROOT / "data/reference/overseas_report_evidence.csv"
BAND_LOW_COEF, BAND_HIGH_COEF = 0.90, 1.10
BETA_BY_TIER = {"L1": 0.9, "L2": 1.0, "L3": 1.3, "L4": 1.3}
TERMINAL_EXCESS_BY_TIER = {"L1": 0.06, "L2": 0.03, "L3": 0.0, "L4": 0.0}
ROE_YEARS, MIN_YEARS, IROE_CAP, G0_CAP, G0_FLOOR = 5, 3, 0.40, 0.25, 0.0
N_FADE, N1, MIN_TERMINAL_SPREAD, PEAK_K, PEAK_RAMP, TRAIL_WEIGHT = 10, 0, 0.02, 1.6, 0.3, 0.0
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
    "00316": dict(erp="erp_hk", ccy="HKD", adr=1, fx="fx_cny_hkd", fx_inv=False),
    "00267": dict(erp="erp_hk", ccy="HKD", adr=1, fx="fx_cny_hkd", fx_inv=False),
}
FINANCIAL_KEEP = {"BRK.B": "金融资本型（保险浮存金＋控股）：ROIC 口径的投入资本/NOPAT 对金融企业不可定义，与 A 股「金融企业退回权益口径」同规；沿用档案 §6.5.2 J 隐含 PB 带，不按 ROIC 重算",
                  "00267": "金融资本型（银行并表、归母利润约八成来自中信银行）：ROIC 口径的投入资本/NOPAT 对金融企业不可定义，与 A 股「金融企业退回权益口径」同规；东财 HK F10 三表自 2014 年起为银行格式（营业额与股东权益字段为空），ROIC 路径被拒。沿用档案 §6.5.2 J 隐含 PB 带，不按 ROIC 重算"}
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
    # ---- §6.5.2.3 锚（A 股生产口径 ratio_bps）：比率 = 各年 NOPAT ÷ 当年母公司权益，锚 = ratio0 × 当期 BPS。
    # 季报观察点的「当期」= 最新年报比率 × f，f = NOPAT TTM ÷ 最新年报 NOPAT；λ 与三年／五年／十年中位只取年报。
    ratios = [y.nopat / y.parent_equity for y in history if y.nopat is not None and y.parent_equity and y.parent_equity > 0]
    if not ratios:
        res["reason"] = "无可用的 NOPAT/母公司权益比率"; return res
    long_hist = years[-10:]
    long_ratios = [y.nopat / y.parent_equity for y in long_hist if y.nopat is not None and y.parent_equity and y.parent_equity > 0]
    f_ttm = 1.0
    if latest is not annual_latest and latest.nopat is not None and annual_latest.nopat and annual_latest.nopat > 0:
        f_ttm = latest.nopat / annual_latest.nopat
    r_cur = ratios[-1] * f_ttm
    # 周期守卫坡道（OI-088）与谷底对称守卫（OI-090）：s = 当期比率 ÷ 十年中位，
    # w = clip((s − (K − ramp)) / (2·ramp), 0, 1)，v 同式取 1/s；ramp = 0 退回单点阈值。
    peak_s = None
    if len(long_ratios) >= 4 and r_cur > 0 and statistics.median(long_ratios) > 0:
        peak_s = r_cur / statistics.median(long_ratios)
    peak_w = trough_w = 0.0
    if peak_s is not None and PEAK_RAMP > 0:
        peak_w = min(1.0, max(0.0, (peak_s - (PEAK_K - PEAK_RAMP)) / (2 * PEAK_RAMP)))
        trough_w = min(1.0, max(0.0, (1.0 / peak_s - (PEAK_K - PEAK_RAMP)) / (2 * PEAK_RAMP)))
    elif peak_s is not None:
        peak_w = 1.0 if peak_s > PEAK_K else 0.0
        trough_w = 1.0 if 1.0 / peak_s > PEAK_K else 0.0
    nopat_cyclical = peak_w >= 0.5
    # 增长态信任度 λ = 近两次年度变动中上行次数 ÷ 2（graded）；非周期锚 = 三年中位 + λ×(当期 − 三年中位)；
    # 周期锚 = 五年中位；ratio0 = (1−max(w,v))×非周期锚 + max(w,v)×周期锚（w=v=0 且 λ=1 即 ttm_growth、λ=0 即 median3）。
    trust = (sum(1 for i in (-1, -2) if ratios[i] > ratios[i - 1]) / 2.0) if len(ratios) >= 3 else 0.0
    base3 = statistics.median(ratios[-3:])
    ratio_noncyc = base3 + trust * (r_cur - base3)
    ratio_cyc = statistics.median(ratios)
    w_any = max(peak_w, trough_w)
    ratio0 = (1.0 - w_any) * ratio_noncyc + w_any * ratio_cyc
    if len(ratios) < 3:
        mode = "median"
    elif w_any >= 1.0:
        mode = "cyclical_median" if peak_w >= trough_w else "trough_median"
    elif w_any <= 0.0 and trust >= 1.0:
        mode = "ttm_growth"
    elif w_any <= 0.0 and trust <= 0.0:
        mode = "median3"
    else:
        mode = f"blend(λ={trust:.1f},w={peak_w:.2f},v={trough_w:.2f})"
    bps = latest.parent_equity / shares
    nopat_ps = ratio0 * bps
    # §6.5.1 第 3 条股权桥（OI-128，与 A 股同口径）：少数股东扣减 = max(账面, m×(EV − 净金融负债))。
    # 海外三表无少数股东损益，m 退回账面份额 少数股东权益÷权益合计（`roic_inputs.minority_share` 的 book_fallback）。
    fin_nd_ps = (latest.interest_debt - latest.excess_cash) / shares
    minority_book_ps = latest.minority_equity / shares
    m_share = (min(max(latest.minority_equity / latest.total_equity, 0.0), roic_inputs.MINORITY_SHARE_CAP)
               if latest.total_equity and latest.total_equity > 0 else 0.0)

    def bridge(ev_ps: float) -> float:
        total_equity = ev_ps - fin_nd_ps
        minority = max(minority_book_ps, m_share * total_equity) if (m_share > 0 and total_equity > 0) else minority_book_ps
        return fin_nd_ps + minority

    net_debt_ps = bridge(nopat_ps / w) if w else fin_nd_ps + minority_book_ps
    if nopat_ps <= 0:
        res["reason"] = "正常化每股 NOPAT 非正"; return res
    v_zero = nopat_ps / w - net_debt_ps
    roic_ok = roic0 is not None and roic0 > g_terminal + MIN_TERMINAL_SPREAD
    common = dict(r=r, rf=rf, erp=erp, beta=beta, rd=rd, tax=tax, wacc=w, roic0=roic0, iroic=iroic, rr=rr,
                  ratio0=ratio0, mode=mode, nopat_ps=nopat_ps, net_debt_ps=net_debt_ps, bps=bps, shares=shares,
                  g_terminal=g_terminal, cyclical=nopat_cyclical, years=[y.period[:4] for y in history], v_zero=v_zero,
                  ratios=ratios, ratio_cur=r_cur, f_ttm=f_ttm,
                  long_median=(statistics.median(long_ratios) if long_ratios else None),
                  buyback_latest=getattr(latest, "buybacks", 0.0) or 0.0,
                  current_period=(latest.period if latest is not annual_latest else ""),
                  peak_s=peak_s, peak_w=peak_w, trough_w=trough_w, trust=trust, base3=base3,
                  ratio_noncyc=ratio_noncyc, ratio_cyc=ratio_cyc)
    if not roic_ok:
        if v_zero <= 0:
            res["reason"] = f"零增长股权价值 {v_zero:.2f} ≤ 0：净负债超过零增长企业价值"; res.update(common); return res
        res.update(common, status="ok", path="zero_growth", value=v_zero, g0=0.0, roic_t=None, terminal_share=1.0)
        return res
    g_capital = min(iroic, IROE_CAP) * min(rr, 1.0) if (rr is not None and iroic is not None and iroic > 0 and rr > 0) else None
    # 增速腿 × (1−w) × d（OI-088／OI-089）：d = min(1, 最新年报 NOPAT/上年) × min(1, TTM NOPAT/最新年报 NOPAT)
    g_trail, cagr, damp = None, roic_inputs.trailing_nopat_cagr(history), 1.0
    ordered_np = [y.nopat for y in history if y.nopat is not None]
    if len(ordered_np) >= 2 and ordered_np[-1] > 0 and ordered_np[-2] > 0:
        damp = min(1.0, ordered_np[-1] / ordered_np[-2])
    if latest is not annual_latest and latest.nopat and annual_latest.nopat and annual_latest.nopat > 0:
        damp *= max(0.0, min(1.0, latest.nopat / annual_latest.nopat))
    if cagr is not None and cagr > 0 and (1.0 - peak_w) > 0:
        g_trail = cagr * TRAIL_WEIGHT * (1.0 - peak_w) * damp
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
    net_debt_ps = bridge(iv.intrinsic_value)
    common["net_debt_ps"] = net_debt_ps
    value = iv.intrinsic_value - net_debt_ps
    if value <= 0:
        res["reason"] = f"股权价值 {value:.2f} ≤ 0：净负债 {net_debt_ps:.2f} 超过企业价值 {iv.intrinsic_value:.2f}"; res.update(common); return res
    res.update(common, status="ok", path="growth", value=value, g0=g0, g_src=g_src, g_capital=g_capital, g_trail=g_trail,
               cagr=cagr, damp=damp, roic_t=roic_t, terminal_share=iv.terminal_share, ev_ps=iv.intrinsic_value)
    return res


def derivation_text(code: str, r: dict, meta: dict, cfg: dict, fx: float, value_trade: float | None, ccy_report: str) -> str:
    if r["status"] != "ok":
        base = f"ROIC 口径（§6.5.2.3，与 A 股生产参数同式）不可算：{r['reason']}"
        if r.get("wacc"):
            base += f"；已算到 WACC {r['wacc']:.2%}（r={r['r']:.2%}=rf {r['rf']:.2%}+β{r['beta']}×ERP {r['erp']:.2%}，rd {r['rd']:.2%}，t {r['tax']:.0%}）"
        return base
    g_line = ("零增长：V = NOPAT/股 ÷ WACC − 净负债/股" if r["path"] == "zero_growth" else
              f"增长 g0={r['g0']:.1%}（来源 {r['g_src']}：资本腿 {('%.1f%%' % (r['g_capital']*100)) if r.get('g_capital') is not None else '—'}=min(增量ROIC {('%.1f%%' % (r['iroic']*100)) if r['iroic'] is not None else '—'},40%)×再投资率 {('%.0f%%' % (r['rr']*100)) if r['rr'] is not None else '—'}，增速腿 {('%.1f%%' % (r['g_trail']*100)) if r.get('g_trail') is not None else '—'}"
              f"{('=CAGR %.1f%%×(1−w %.2f)×d %.2f' % (r['cagr']*100, r['peak_w'], r['damp'])) if r.get('g_trail') is not None else ''}），ROIC_T=min(WACC+档位超额, ROIC0)={r['roic_t']:.1%}，g_T={r['g_terminal']:.1%}，fade {N_FADE} 年，终值占比 {r['terminal_share']:.0%}")
    fx_line = (f"；报表币 {ccy_report} → 交易币 {cfg['ccy']} 汇率 {fx:.4f}" + (f"，每 ADR {cfg['adr']} 股" if cfg['adr'] != 1 else "")) if (ccy_report != cfg["ccy"] or cfg["adr"] != 1) else ""
    ratio_txt = "／".join(f"{v:.3f}" for v in r["ratios"])
    guard_txt = (f"周期守卫 NOPAT/母公司权益：当期 {r['ratio_cur']:.3f}（最新年报 {r['ratios'][-1]:.3f} × f {r['f_ttm']:.2f}）vs 十年中位 {r['long_median']:.3f}"
                 f" = {r['peak_s']:.2f}×，坡道 w={r['peak_w']:.2f}／谷 v={r['trough_w']:.2f}" if r.get("peak_s") is not None else "周期守卫：无可比比率（w=v=0）")
    anchor_txt = (f"信任度 λ={r['trust']:.1f}，非周期锚 = 三年中位 {r['base3']:.3f} + λ×(当期 − 三年中位) = {r['ratio_noncyc']:.3f}，"
                  f"五年中位 {r['ratio_cyc']:.3f}，ratio0 = (1−max(w,v))×非周期锚 + max(w,v)×五年中位")
    period_text = (f"财年 {r['years'][0]}~{r['years'][-1]}＋截至 {r['current_period']} TTM"
                   if r.get("current_period") else f"财年 {r['years'][0]}~{r['years'][-1]}")
    return (f"ROIC·{'增长' if r['path']=='growth' else '零增长'}（§6.5.2.3 同口径，{period_text}，{meta.get('source','')}）："
            f"NOPAT/母公司权益财年序列 {ratio_txt} → ratio0 **{r['ratio0']:.3f}**（{r['mode']}）× 当期 BPS {r['bps']:.2f}（母公司权益 ÷ 稀释股数 {r['shares']/1e6:,.0f}m）= 每股 NOPAT 锚 **{r['nopat_ps']:.3f}**；{guard_txt}；{anchor_txt}；"
            f"最新观察点回购 {r['buyback_latest']/1e9:.1f}b；"
            f"ROIC0 {r['roic0']:.1%}；WACC {r['wacc']:.2%}（r {r['r']:.2%} = rf {r['rf']:.2%} + β{r['beta']}×ERP {r['erp']:.2%}；rd {r['rd']:.2%}；t {r['tax']:.0%}；账面权重）；{g_line}；"
            f"净负债/股 {r['net_debt_ps']:.3f}（有息负债−超额现金＋少数股东扣减，扣减取账面与账面份额×权益价值较大者）；**V = {r['value']:.3f} {ccy_report}/普通股**{fx_line}"
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
        print(f"{code:<8}{name:<14}{tier:<4}{status:<12}{(format(r['value'], '.2f') if status in ('ok',) else '—'):>12}{(format(v_trade, ',.2f') if v_trade else '—'):>12}{(f'{price:,.2f}' if price else '—'):>10}{(f'{pv:.3f}' if pv else '—'):>7}  {method}{'' if status=='ok' else '：' + text[:90]}")
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
        if price:
            row["valuation_price"] = f"{price:.2f}" if cfg["ccy"] != "KRW" else f"{price:.0f}"
            row["valuation_price_as_of"] = price_as_of or args.as_of
        row["valuation_reason"] = (str(row.get("valuation_reason", "")).split("｜**本次定档")[0]
                                   + f"｜**本次定档（{evidence_date or '证据日缺失'}，{evidence_event or '定期报告'}，ROIC 口径）**：{method}；带 "
                                   + ("—" if lo is None else f"{lo:,.2f}~{hi:,.2f}") + f"；复核时点价 {row.get('valuation_price') or 'NA'}（{row.get('valuation_price_as_of') or 'NA'}）。")
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
                   f"带 {row.get('fair_price_low') or '—'}~{row.get('fair_price_high') or '—'} {row.get('currency','')}。\n\n{row['band_derivation_text']}\n")
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
