#!/usr/bin/env python3
"""历史估值带重建：逐季财务 → 内在价值 → 每股每日估值状态（OI-034 第 1 步）。

它做什么
--------
用户 2026-08-07 给定的回测方案第 1 步：**「对每个股票，每年四次定期报告，基于每次定期
报告计算估值带，每个带对应一段时间，完成后每个股票每天都有对应的估值状态。」**

本脚本把三份已落地的原始数据接起来：

    data/raw/financials/<报告期>.csv     逐季财务（§12.4.2，含 notice_date）
    data/raw/corporate_actions/*.csv     分红送转（§12.4.1）
    data/raw/ohlcv/<代码>.csv            不复权日线（§12.4.1）
        ↓  scripts/intrinsic_value.py（§6.5.7.2）
    每股 × 每个报告期 → 一条带；每股 × 每个交易日 → 一个估值状态

**这一步的价值大于回测本身**：它是消除 §12.4 估值闸门前视豁免的前提——历史带从此可按
「当时已披露的数据」重建，而不必再借用当前的带去还原历史某天的矩阵资格。

四个已实测到的坑（都不是假想，样本里全部真实出现过）
--------------------------------------------------
1. **公告日不单调**。九号公司 2019 年各期是上市时补披露的：`2019-12-31` 公告于
   2020-06-03，却早于 `2019-06-30` 的 2020-09-30。故「某天该用哪条带」**不能**按报告期
   顺序取，必须取「所有 `available_at ≤ 当日` 的带里报告期最新的那条」。

2. **TTM 需要三期，而三期的公告日不一定都早于本期公告日**。TTM(Q1) = Q1 + 上年报 −
   上年 Q1，而年报常与一季报同期披露（甚至更晚）。故本脚本的生效日取
   **`available_at = max(所用各期的公告日)`**，不是本期公告日——否则就是 §12.4 前视。

3. **`weightavg_roe = 0` 是缺失值伪装成数字**。九号公司 2019 年报净利 −4.5 亿、ROE 却
   写 0。凡净利非零而 ROE 恰为 0 一律当缺失（§15.2 第 3 条：静默失效已复发五次）。

4. **不复权价 × 送转 = 带与价不同基**。带由报告期的每股口径算出，其后若发生 10 转 10，
   原始价格腰斩而带不动，估值状态凭空腰斩。故按 `share_ratio` 逐日折算带的股本基准。

口径选择（**这些是判断，不是数据，需用户确认**）
----------------------------------------------
* `r` 按 §6.5.7.1 的质量分档区间取中位：L1 → 8%｜L2 → 10%｜L3 → 13%。始终附敏感度。
* `ROE_T` 终值 ROE：L1 → 15%｜L2 → 12%｜L3 → 10%（竞争终将压低超额 ROE）。
* `g_T` = 3%（名义 GDP 量级），`N` = 10 年线性 fade。
* **`N=10` 是衰减期不是高增长期**：§6.5.7.1 v1.56 硬规则限制的 `n1` 是「增速维持不变的
  年数」，本模型 g 自第 1 年即开始衰减，`n1` 实为 0，故不与该规则冲突。
* `g0` 两种口径都算，默认用哪个见 `--g0-source`：
  - `trailing`：归母净利 TTM 的三年 CAGR。**是外推**（§15.2 第 6 条的形态之一）。
  - `sustainable`：`ROE_TTM × (1 − 近三年派息率均值)`，即可内生维持的增长。**不外推**，
    且与模型的再投资关系自洽。

用法::

    python3 scripts/build_historical_valuation_bands.py --sample          # 10 只样本可行性验证
    python3 scripts/build_historical_valuation_bands.py --codes 600519,600809
    python3 scripts/build_historical_valuation_bands.py --all --out-bands ... --out-daily ...
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from intrinsic_value import (  # noqa: E402
    DEFAULT_G_TERMINAL,
    ValuationError,
    intrinsic_value,
    valuation_label,
)

FIN_DIR = ROOT / "data/raw/financials"
OHLCV_DIR = ROOT / "data/raw/ohlcv"
ACTIONS = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"
TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"

# §6.5.7.2：现值锚已含要求回报，系数取 [0.90, 1.10] 而非 [0.85, 1.05]（避免二次保守）。
BAND_LOW_COEF, BAND_HIGH_COEF = 0.90, 1.10

# §6.5.7.1 的 r 分档区间取中位；ROE_T 为终值 ROE。**判断值，非观测值。**
TIER_PARAMS = {
    "L1": {"r": 0.08, "roe_terminal": 0.15},
    "L2": {"r": 0.10, "roe_terminal": 0.12},
    "L3": {"r": 0.13, "roe_terminal": 0.10},
}
DEFAULT_TIER = "L2"

# 可行性验证样本：刻意覆盖每一种已知失败形态，不是随机抽的。
SAMPLE_CODES = [
    "600519",  # 贵州茅台 L1 高 ROE 稳态
    "600809",  # 山西汾酒 L1 高增长后减速
    "300750",  # 宁德时代 L1 超高增长、上市晚
    "601899",  # 紫金矿业 L2 资源周期
    "000423",  # 东阿阿胶 L2 **2019 年亏损**
    "300628",  # 亿联网络 L2 稳定增长
    "600690",  # 海尔智家 L2 低增长成熟
    "000425",  # 徐工机械 L2 机械周期
    "689009",  # 九号公司 L2 **上市前补披露、公告日不单调、早年亏损**
    "300474",  # 景嘉微 L3 **利润极薄**、战术层
]

QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))


# ------------------------------------------------------------------ 载入
def _num(value: str | None) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_financials(codes: set[str] | None) -> dict[str, dict[str, dict]]:
    """{代码: {报告期: 行}}。`codes=None` 取全市场。"""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for path in sorted(FIN_DIR.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                code = row["security_code"]
                if codes is not None and code not in codes:
                    continue
                if not (row.get("notice_date") or "").strip():
                    continue  # §12.4：无公告日的行不可用于历史建带
                out[code][row["report_date"]] = row
    return out


def load_actions() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    if not ACTIONS.exists():
        return out
    with ACTIONS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out[row["security_code"]].append(row)
    for rows in out.values():
        rows.sort(key=lambda r: r.get("ex_dividend_date") or "")
    return out


def load_tiers() -> dict[str, dict]:
    if not TIERS.exists():
        return {}
    with TIERS.open(newline="", encoding="utf-8") as handle:
        return {r["security_code"]: r for r in csv.DictReader(handle)}


def load_ohlcv(code: str) -> list[tuple[str, float]]:
    path = OHLCV_DIR / f"{code}.csv"
    if not path.exists():
        return []
    out = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            close = _num(row.get("close"))
            if close is not None and close > 0:
                out.append((row["date"], close))
    out.sort()
    return out


# ------------------------------------------------------------------ TTM
def prior_periods(period: str) -> tuple[str, str] | None:
    """TTM 需要的另外两期：(上年年末, 上年同期)。年报期返回 None（自身即 TTM）。"""
    year, month, day = int(period[:4]), int(period[5:7]), int(period[8:10])
    if (month, day) == (12, 31):
        return None
    return f"{year - 1}-12-31", f"{year - 1}-{month:02d}-{day:02d}"


@dataclass
class TTMValue:
    value: float
    evidence_dates: list[str]   # 所用各期的公告日 —— 生效日取其 max（坑 2）


def ttm(series: dict[str, dict], period: str, field: str) -> TTMValue | None:
    """报告期口径为**年初至今累计**，故 TTM = 本期 + 上年年报 − 上年同期。"""
    row = series.get(period)
    if row is None:
        return None
    current = _num(row.get(field))
    if current is None:
        return None
    dates = [row["notice_date"]]
    pair = prior_periods(period)
    if pair is None:
        return TTMValue(current, dates)
    total = current
    for key, sign in zip(pair, (1.0, -1.0)):
        other = series.get(key)
        if other is None:
            return None
        value = _num(other.get(field))
        if value is None:
            return None
        total += sign * value
        dates.append(other["notice_date"])
    return TTMValue(total, dates)


def roe_ttm(series: dict[str, dict], period: str) -> TTMValue | None:
    """`weightavg_roe` 的 TTM 滚动，返回**小数**。

    坑 3：净利非零而 ROE 恰为 0 的行是缺失值伪装成数字，剔掉而不是当 0 用。
    """
    for key in filter(None, (period,) + (prior_periods(period) or ())):
        row = series.get(key)
        if row is None:
            return None
        roe, profit = _num(row.get("weightavg_roe")), _num(row.get("parent_netprofit"))
        if roe is None:
            return None
        if roe == 0 and profit not in (None, 0):
            return None
    result = ttm(series, period, "weightavg_roe")
    return TTMValue(result.value / 100.0, result.evidence_dates) if result else None


def derive_roe(series: dict[str, dict], period: str,
               eps: TTMValue | None) -> tuple[TTMValue | None, str]:
    """TTM ROE，优先用 `weightavg_roe` 滚动；不可得时退回 `EPS_TTM / BPS`。

    退回口径存在的理由：`weightavg_roe` 的伪 0（坑 3）会**向后污染四个季度**——上年同期
    是伪 0，本期滚动就算不出来。而 `BPS` 是时点值不受此影响。实测九号公司 2021 年上半年
    两期正因此被误判为「输入不全」，退回口径可救回。两者口径不同（加权平均净资产 vs 期末
    净资产），故逐行记 `roe_source`，不混作一谈。
    """
    primary = roe_ttm(series, period)
    if primary is not None:
        return primary, "weightavg_ttm"
    bps = _num(series[period].get("bps"))
    if eps is None or bps is None or bps <= 0:
        return None, ""
    return TTMValue(eps.value / bps, eps.evidence_dates + [series[period]["notice_date"]]), "eps_over_bps"


def normalized_roe(series: dict[str, dict], available_at: str, years: int = 5,
                   stat: str = "median") -> tuple[float | None, int]:
    """近 `years` 个已披露财年的**年度 ROE 中位数**——模型里的 ROE 是结构参数不是周期读数。

    为什么需要它：本模型把当期 TTM 当作永续路径的起点，故**在盈利低谷读到的低 EPS 与低
    ROE 会被外推十年**，内在价值随之塌陷，股票恰在底部显示「最贵」。实测东阿阿胶
    2020-12-31（EPS_TTM 0.07、ROE 0.44%）被算出隐含 PE **201**、徐工机械 2016-12-31 得 86
    ——两者都是周期低谷。用中位数 ROE 归一化可消除这一顺周期陷阱。
    """
    values = []
    for period in fiscal_years_before(series, available_at, years):
        row = series[period]
        roe, profit = _num(row.get("weightavg_roe")), _num(row.get("parent_netprofit"))
        if roe is None or (roe == 0 and profit not in (None, 0)):
            continue
        values.append(roe / 100.0)
    if not values:
        return None, 0
    agg = statistics.median if stat == "median" else statistics.fmean
    return agg(values), len(values)


# ------------------------------------------------------------------ 输入推导
def fiscal_years_before(series: dict[str, dict], available_at: str, count: int) -> list[str]:
    """公告日 ≤ `available_at` 的最近 `count` 个年报期（降序）。"""
    annuals = [p for p in series if p.endswith("-12-31") and series[p]["notice_date"] <= available_at]
    return sorted(annuals, reverse=True)[:count]


def payout_ratio(series: dict[str, dict], actions: list[dict], available_at: str,
                 years: int = 3) -> tuple[float | None, int]:
    """近 `years` 个已披露财年的派息率**逐年均值**（返回 (均值, 样本年数)）。

    逐年算再平均、而不是三年现金合计除三年 EPS 合计——后者在期间发生送转时不同基。
    """
    ratios = []
    for period in fiscal_years_before(series, available_at, years):
        eps = _num(series[period].get("basic_eps"))
        if eps is None or eps <= 0:
            continue
        cash = sum(_num(a.get("cash_per_share")) or 0.0
                   for a in actions if a.get("report_date") == period)
        ratios.append(min(max(cash / eps, 0.0), 1.0))
    return (statistics.fmean(ratios) if ratios else None), len(ratios)


def trailing_cagr(series: dict[str, dict], period: str, years: int = 3) -> float | None:
    """归母净利 TTM 的 `years` 年 CAGR。基期非正则不可算（负基数的增长率无意义）。"""
    base_period = f"{int(period[:4]) - years}{period[4:]}"
    now, base = ttm(series, period, "parent_netprofit"), ttm(series, base_period, "parent_netprofit")
    if now is None or base is None or base.value <= 0 or now.value <= 0:
        return None
    return (now.value / base.value) ** (1.0 / years) - 1.0


# ------------------------------------------------------------------ 送转折算
def split_factor(actions: list[dict], since: str, until: str) -> float:
    """`(since, until]` 内累计送转比：带需除以它才与不复权价同基（坑 4）。

    **`since` 必须取该期的公告日，不是报告期末**。实测亿联网络 2019-07-09 除权 10 转 10，
    其 `2019-06-30` 报告公告于 2019-08-15（除权之后），BPS 由上期 12.46 直接降到 6.25
    ——**东财按公告时的股本列示，该期报告本身已是除权后口径**。若按报告期末起算，这一期
    会被再除一次 2.0，内在价值凭空腰斩（首版实测 16.07 → 8.07，即此错）。
    """
    factor = 1.0
    for action in actions:
        ex_date = action.get("ex_dividend_date") or ""
        if since < ex_date <= until:
            factor *= 1.0 + (_num(action.get("share_ratio")) or 0.0)
    return factor


# ------------------------------------------------------------------ 建带
@dataclass
class Band:
    code: str
    name: str
    report_date: str
    notice_date: str
    available_at: str
    status: str
    reason: str = ""
    eps_ttm: float | None = None
    roe_ttm: float | None = None
    roe_source: str = ""
    eps0: float | None = None      # 实际喂给模型的 EPS（归一化口径下 ≠ eps_ttm）
    roe0: float | None = None      # 实际喂给模型的 ROE
    bps: float | None = None
    g_trailing: float | None = None
    g_sustainable: float | None = None
    payout: float | None = None
    g0: float | None = None
    g0_capped: bool = False
    r: float | None = None
    roe_terminal: float | None = None
    value: float | None = None
    band_low: float | None = None
    band_high: float | None = None
    terminal_share: float | None = None
    implied_pe: float | None = None
    min_payout: float | None = None


def build_band(code: str, name: str, tier: str, series: dict[str, dict], actions: list[dict],
               period: str, args) -> Band:
    row = series[period]
    notice = row["notice_date"]

    eps = ttm(series, period, "basic_eps")
    roe, roe_source = derive_roe(series, period, eps)
    bps = _num(series[period].get("bps"))

    # 坑 2：生效日 = **所用**各期公告日的最大值。归一化口径只用本期 BPS 与更早的年报 ROE，
    # 故其生效日就是本期公告日；TTM 口径要用上年年报，才可能被推后。
    evidence = [notice]
    if args.roe_source == "ttm":
        if eps is None:
            reason = ("取数窗口起点之前（非缺陷）" if period[:4] == args.since[:4]
                      else "TTM EPS 所需三期不全")
            return Band(code, name, period, notice, notice, "unavailable", reason)
        if roe is None:
            return Band(code, name, period, notice, notice, "unavailable", "TTM ROE 不可得（伪 0 且无 BPS 可退回）")
        evidence += eps.evidence_dates + roe.evidence_dates
    available_at = max(evidence)

    params = TIER_PARAMS.get(tier, TIER_PARAMS[DEFAULT_TIER])
    r, roe_t = params["r"], params["roe_terminal"]

    band = Band(code, name, period, notice, available_at, "unavailable",
                eps_ttm=eps.value if eps else None, roe_ttm=roe.value if roe else None,
                roe_source=roe_source, bps=bps,
                g_trailing=trailing_cagr(series, period), r=r, roe_terminal=roe_t)

    # 归一化口径：ROE 取近五年年度中位（结构参数），EPS 由清洁盈余 E = ROE×B 反推。
    # 这样两个输入天然自洽，且不把周期低谷的读数外推十年（见 normalized_roe 文档）。
    if args.roe_source == "normalized":
        roe0, years = normalized_roe(series, available_at, args.roe_years, args.roe_stat)
        if roe0 is None or bps is None or bps <= 0:
            band.reason = ("归一化 ROE 不可算：无已披露年报 ROE" if roe0 is None else
                           f"BPS={bps} 不可用")
            return band
        if years < args.min_roe_years:
            band.reason = f"已披露年报 ROE 仅 {years} 年 < 要求 {args.min_roe_years} 年"
            return band
        eps0 = roe0 * bps
    else:
        roe0, eps0 = roe.value, eps.value
    band.roe0, band.eps0 = roe0, eps0

    # 亏损与负 ROE 是**经济学上的拒绝**，不是数据缺失——先判，免得混进「输入不全」把
    # 护栏拒绝率算低了（用户要量的正是这个比例）。
    if eps0 <= 0 or roe0 <= 0:
        band.status = "rejected"
        band.reason = (f"EPS0={eps0:.4f}／ROE0={roe0:.2%} 非正：按盈利折现无意义，"
                       f"须走 §6.5.5.2 逐票建档")
        return band

    # g_sustainable 必须用**模型实际采用的 roe0**，否则归一化了 ROE 却拿周期读数算增长，
    # 两个输入自相矛盾（首版即犯：低谷年 ROE 为负 → g 算不出 → 整期被判「输入不全」）。
    payout, _years = payout_ratio(series, actions, available_at)
    band.payout = payout
    band.g_sustainable = roe0 * (1 - payout) if payout is not None else None

    g0 = band.g_trailing if args.g0_source == "trailing" else band.g_sustainable
    if g0 is None:
        band.reason = f"g0（{args.g0_source}）不可算：近三年无正 EPS 财年可算派息率"
        return band

    g0 = max(g0, args.g0_floor)
    if g0 > args.g0_cap:
        g0, band.g0_capped = args.g0_cap, True
    band.g0 = g0

    try:
        result = intrinsic_value(eps0, roe0, g0, r, roe_terminal=roe_t,
                                 g_terminal=args.g_terminal, n=args.n)
    except ValuationError as exc:
        band.status, band.reason = "rejected", str(exc)
        return band

    band.status = "ok"
    band.value = result.intrinsic_value
    band.band_low = BAND_LOW_COEF * result.intrinsic_value
    band.band_high = BAND_HIGH_COEF * result.intrinsic_value
    band.terminal_share = result.terminal_share
    band.implied_pe = result.implied_pe
    band.min_payout = result.min_payout
    return band


def applicable_bands(bands: list[Band]) -> list[Band]:
    """坑 1：公告日不单调，故某天适用的带 = 所有 `available_at ≤ 当日` 中**报告期最新**的。

    按 available_at 排序后单调扫描，丢弃「已被更新报告期覆盖」的带；返回可直接二分的序列。
    """
    ordered = sorted([b for b in bands if b.status == "ok"], key=lambda b: (b.available_at, b.report_date))
    kept: list[Band] = []
    best = ""
    for band in ordered:
        if band.report_date <= best:
            continue  # 迟到的旧报告期：披露时已被更新的报告期取代，永远轮不到它
        best = band.report_date
        if kept and kept[-1].available_at == band.available_at:
            kept[-1] = band
        else:
            kept.append(band)
    return kept


def daily_states(code: str, bands: list[Band], prices: list[tuple[str, float]],
                 actions: list[dict]) -> list[dict]:
    usable = applicable_bands(bands)
    if not usable or not prices:
        return []
    keys = [b.available_at for b in usable]
    out = []
    for date, close in prices:
        index = bisect_right(keys, date) - 1
        if index < 0:
            continue
        band = usable[index]
        # 坑 4：带按**公告时**的股本口径，价格是不复权的 → 按公告后的送转折算带
        factor = split_factor(actions, band.notice_date, date)
        low, high = band.band_low / factor, band.band_high / factor
        value = band.value / factor
        out.append({
            "security_code": code,
            "date": date,
            "close": f"{close:.4f}",
            "band_report_date": band.report_date,
            "band_available_at": band.available_at,
            "split_factor": f"{factor:.6f}",
            "intrinsic_value": f"{value:.4f}",
            "band_low": f"{low:.4f}",
            "band_high": f"{high:.4f}",
            "valuation_ratio": f"{close / value:.4f}",
            "upside_to_low": f"{low / close - 1:.4f}",
            "valuation_label": valuation_label(close, value),
        })
    return out


# ------------------------------------------------------------------ 输出
BAND_FIELDS = ["security_code", "security_name", "quality_tier", "report_date", "notice_date",
               "available_at", "status", "reason", "eps_ttm", "roe_ttm", "roe_source", "bps",
               "eps0", "roe0", "payout", "g_trailing", "g_sustainable", "g0", "g0_capped",
               "r", "roe_terminal", "intrinsic_value", "band_low", "band_high",
               "implied_pe", "pe_on_ttm_eps", "terminal_share", "min_payout"]


def band_row(band: Band, tier: str) -> dict:
    def fmt(value, digits=4):
        return "" if value is None else f"{value:.{digits}f}"
    pe_ttm = (band.value / band.eps_ttm) if (band.value and band.eps_ttm and band.eps_ttm > 0) else None
    return {
        "security_code": band.code, "security_name": band.name, "quality_tier": tier,
        "report_date": band.report_date, "notice_date": band.notice_date,
        "available_at": band.available_at, "status": band.status, "reason": band.reason,
        "eps_ttm": fmt(band.eps_ttm), "roe_ttm": fmt(band.roe_ttm),
        "roe_source": band.roe_source, "bps": fmt(band.bps),
        "eps0": fmt(band.eps0), "roe0": fmt(band.roe0), "payout": fmt(band.payout),
        "g_trailing": fmt(band.g_trailing), "g_sustainable": fmt(band.g_sustainable),
        "g0": fmt(band.g0), "g0_capped": "Y" if band.g0_capped else "",
        "r": fmt(band.r, 3), "roe_terminal": fmt(band.roe_terminal, 3),
        "intrinsic_value": fmt(band.value), "band_low": fmt(band.band_low),
        "band_high": fmt(band.band_high), "implied_pe": fmt(band.implied_pe, 2),
        "pe_on_ttm_eps": fmt(pe_ttm, 2),
        "terminal_share": fmt(band.terminal_share), "min_payout": fmt(band.min_payout),
    }


def refresh_jumps(bands: list[Band]) -> list[float]:
    """相邻两条生效带之间内在价值的对数跳变——**换带当天估值锚被改写多少**。

    这是 OI-034 「每天按空间排序买前十」能否成立的关键量：若季度换带动辄跳 30%+，
    排序会在换带日整体重排，回测出的收益大半来自换带时点而非价格。
    """
    usable = applicable_bands(bands)
    out = []
    for previous, current in zip(usable, usable[1:]):
        if previous.value and current.value:
            out.append(abs(math.log(current.value / previous.value)))
    return out


def report(all_bands: list[tuple[str, Band]], daily_counts: dict[str, int],
           price_counts: dict[str, int], args) -> None:
    bands = [b for _, b in all_bands]
    total = len(bands)
    ok = [b for b in bands if b.status == "ok"]
    rejected = [b for b in bands if b.status == "rejected"]
    unavailable = [b for b in bands if b.status == "unavailable"]

    print(f"\n{'=' * 78}\n历史带重建可行性报告｜ROE 口径={args.roe_source}｜g0 口径={args.g0_source}"
          f"｜N={args.n}｜g_T={args.g_terminal:.1%}")
    print(f"{'=' * 78}")
    print(f"报告期 × 股票 组合 {total} 个：**成功 {len(ok)}（{len(ok)/total:.0%}）**｜"
          f"护栏拒绝 {len(rejected)}（{len(rejected)/total:.0%}）｜输入不全 {len(unavailable)}（{len(unavailable)/total:.0%}）")

    for label, group in (("护栏拒绝", rejected), ("输入不全", unavailable)):
        if not group:
            continue
        reasons: dict[str, int] = defaultdict(int)
        for band in group:
            key = band.reason.split("：")[0] if "：" in band.reason else band.reason
            reasons[key] += 1
        print(f"\n{label}原因分布：")
        for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {count:>4}  {reason}")

    if ok:
        shares = sorted(b.terminal_share for b in ok)
        over = [b for b in ok if b.terminal_share > 0.75]
        print(f"\n终值占比：中位 {statistics.median(shares):.0%}｜"
              f"P10 {shares[len(shares)//10]:.0%}｜P90 {shares[-max(1,len(shares)//10)]:.0%}｜"
              f"**>75% 有 {len(over)}/{len(ok)}（{len(over)/len(ok):.0%}）**")
        pes = sorted(b.implied_pe for b in ok)
        print(f"隐含 PE：中位 {statistics.median(pes):.1f}｜最小 {pes[0]:.1f}｜最大 {pes[-1]:.1f}")
        capped = [b for b in ok if b.g0_capped]
        print(f"g0 触顶（>{args.g0_cap:.0%}）：{len(capped)}/{len(ok)}（{len(capped)/len(ok):.0%}）")
        both = [b for b in bands if b.g_trailing is not None and b.g_sustainable is not None]
        if both:
            diffs = sorted(b.g_trailing - b.g_sustainable for b in both)
            print(f"两种 g0 口径之差（trailing − sustainable，n={len(both)}）："
                  f"中位 {statistics.median(diffs):+.1%}｜P10 {diffs[len(diffs)//10]:+.1%}｜"
                  f"P90 {diffs[-max(1,len(diffs)//10)]:+.1%}")
        lag = [b for b in ok if b.available_at > b.notice_date]
        print(f"生效日晚于本期公告日（TTM 需更晚的年报，坑 2）：{len(lag)}/{len(ok)}（{len(lag)/len(ok):.0%}）")
        sources: dict[str, int] = defaultdict(int)
        for band in ok:
            sources[band.roe_source or "无 TTM ROE（归一化口径下不影响建带）"] += 1
        print("ROE 取数来源：" + "｜".join(f"{k} {v}" for k, v in sorted(sources.items())))

    grouped: dict[str, list[Band]] = defaultdict(list)
    for code, band in all_bands:
        grouped[code].append(band)
    jumps = [j for group in grouped.values() for j in refresh_jumps(group)]
    if jumps:
        jumps.sort()
        big = [j for j in jumps if j > 0.20]
        print(f"\n换带跳变 |Δln(内在价值)|（n={len(jumps)}）：中位 {statistics.median(jumps):.1%}｜"
              f"P90 {jumps[-max(1, len(jumps)//10)]:.1%}｜最大 {jumps[-1]:.1%}｜"
              f"**>20% 有 {len(big)}（{len(big)/len(jumps):.0%}）**"
              f"\n  ↑ 这是 OI-034「按空间排序买前十」的关键量：跳变越大，回测收益越可能来自换带时点而非价格")

    # 覆盖率的分母必须是**首条带生效后**的交易日：早于首条带的日子本就不该有估值状态，
    # 拿全history当分母会把 2016 年才起算的带说成「只覆盖 38%」。
    print("\n逐股覆盖（成功带数 / 报告期数 → 首带生效后有状态交易日 / 该区间交易日）：")
    per_stock: dict[str, list[Band]] = defaultdict(list)
    names: dict[str, str] = {}
    for code, band in all_bands:
        per_stock[code].append(band)
        names[code] = band.name
    for code in sorted(per_stock):
        group = per_stock[code]
        good = sum(1 for b in group if b.status == "ok")
        days, in_scope = daily_counts.get(code, 0), price_counts.get(code, 0)
        cover = f"{days}/{in_scope}（{days/in_scope:.0%}）" if in_scope else "无可用区间"
        mark = "" if good else "   ← **一条带都没建成**"
        print(f"  {code} {names[code]:<8} {good:>2}/{len(group):<3} → {cover}{mark}")


def main() -> int:
    parser = argparse.ArgumentParser(description="历史估值带重建（OI-034 第 1 步）")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--sample", action="store_true", help="10 只可行性验证样本")
    scope.add_argument("--codes", help="逗号分隔代码")
    scope.add_argument("--all", action="store_true", help="全部有行情的股票")
    parser.add_argument("--since", default="2016-03-31")
    parser.add_argument("--roe-source", choices=("normalized", "ttm"), default="normalized",
                        help="normalized=近五年年度 ROE 中位并由 E=ROE×B 反推 EPS（缺省，避免顺周期陷阱）")
    parser.add_argument("--g0-source", choices=("sustainable", "trailing"), default="sustainable")
    parser.add_argument("--roe-years", type=int, default=5, help="归一化 ROE 的回看年数")
    parser.add_argument("--roe-stat", choices=("median", "mean"), default="median")
    parser.add_argument("--min-roe-years", type=int, default=3,
                        help="归一化 ROE 至少需要几个已披露财年，缺省 3")
    parser.add_argument("--g0-cap", type=float, default=0.25, help="g0 上限，缺省 25%%")
    parser.add_argument("--g0-floor", type=float, default=0.0)
    parser.add_argument("--g-terminal", type=float, default=DEFAULT_G_TERMINAL)
    parser.add_argument("--n", type=int, default=10, help="fade 年数（非高增长年数，见文件头）")
    parser.add_argument("--out-bands", type=Path)
    parser.add_argument("--out-daily", type=Path)
    args = parser.parse_args()

    if args.sample:
        codes = list(SAMPLE_CODES)
    elif args.codes:
        codes = [c.strip().zfill(6) for c in args.codes.split(",") if c.strip()]
    else:
        codes = sorted(p.stem for p in OHLCV_DIR.glob("*.csv"))

    tiers = load_tiers()
    financials = load_financials(set(codes))
    actions = load_actions()
    print(f"历史带重建：{len(codes)} 只｜报告期起点 {args.since}｜g0={args.g0_source}")

    all_bands: list[tuple[str, Band]] = []
    band_rows: list[dict] = []
    daily_rows: list[dict] = []
    daily_counts: dict[str, int] = {}
    price_counts: dict[str, int] = {}

    for code in codes:
        series = financials.get(code, {})
        if not series:
            print(f"  ⚠ {code} 无财务数据，跳过")
            continue
        tier = (tiers.get(code) or {}).get("quality_tier") or DEFAULT_TIER
        name = next(iter(series.values()))["security_name"]
        periods = sorted(p for p in series if p >= args.since)
        bands = [build_band(code, name, tier, series, actions.get(code, []), p, args) for p in periods]
        all_bands.extend((code, b) for b in bands)
        band_rows.extend(band_row(b, tier) for b in bands)

        prices = load_ohlcv(code)
        states = daily_states(code, bands, prices, actions.get(code, []))
        daily_counts[code] = len(states)
        usable = applicable_bands(bands)
        first = usable[0].available_at if usable else None
        price_counts[code] = sum(1 for d, _ in prices if first and d >= first)
        daily_rows.extend(states)

    if args.out_bands:
        args.out_bands.parent.mkdir(parents=True, exist_ok=True)
        with args.out_bands.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=BAND_FIELDS)
            writer.writeheader()
            writer.writerows(band_rows)
        print(f"带已写入 {args.out_bands}（{len(band_rows)} 行）")
    if args.out_daily and daily_rows:
        args.out_daily.parent.mkdir(parents=True, exist_ok=True)
        with args.out_daily.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(daily_rows[0]))
            writer.writeheader()
            writer.writerows(daily_rows)
        print(f"逐日状态已写入 {args.out_daily}（{len(daily_rows):,} 行）")

    report(all_bands, daily_counts, price_counts, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
