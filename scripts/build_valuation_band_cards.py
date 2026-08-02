#!/usr/bin/env python3
"""Compute the §6.6 建带卡 draft for every worth_attention name from local evidence.

工作流 §15 第 1 条：能由脚本稳定完成的必须用脚本。锚定量取数、TTM 差分、
一致预期中位数、股本口径校验、倍数取数、带复算——全部是机械步骤，逐票手算
只会引入 v1.28 刚修掉的那种口径漂移。

This script does NOT create valuation opinions. It computes the mechanical part
of the card (§6.5.2.1) and marks explicitly what still needs外部取证 or judgment:

* `anchor_value`  — per §6.5.2.1 取数口径表 (TTM 差分 / 一致预期中位数 / 周期中枢)
* `multiple_or_rate` — 自身历史中位 (`valuation_band`) 或隐含 PB (J)
* `band_low/high` — per §6.5.2 类型表系数, recomputed by validate_valuation_bands
* `band_sensitivity` — 锚 ±15% 对应的带

Strategy tags come from `--tags` (代码,strategy_tag). Types whose anchor needs
外部取证 (F/K/M/N/P and A-1/H-ebitda) are emitted with `needs_external` set and
an empty anchor — per §6.5.2.1 they are 无法估值 until the evidence is fetched.

Usage::

    python3 scripts/build_valuation_band_cards.py \
      --tags data/interim/strategy_tag_map.csv \
      --out data/interim/valuation_band_cards.csv \
      --as-of 2026-08-01
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "data/interim/valuation_evidence"

# §6.5.2 类型表：tag -> (anchor_metric, shape, (low_coef, high_coef), 本地可算?)
TYPE_SPEC = {
    "A": ("normalized_profit", 1, None, True),                # A-2；系数按分层，见 A2_COEFS
    "C": ("forward_normalized_profit", 1, (1.0, 1.5), True),  # 系数即 PEG 带
    "D": ("normalized_profit_2_3y", 1, (0.90, 1.10), True),   # 锚已是保守现值，带围绕它而非再打折
    "E": ("repaired_normalized_profit", 1, (0.85, 1.00), True),
    "F": ("resource_nav", 1, (0.85, 1.00), True),             # primary 需储量；F-2 兜底本地可算
    "H": ("mid_cycle_profit", 1, (0.85, 1.00), True),
    "J": ("bvps", 1, (0.90, 1.10), True),
    "K": ("dps", 2, (1.0, 1.0), True),                        # primary 需分红率；K-2 兜底同 A-2
    "M": ("sotp_value", 1, (0.90, 1.10), True),               # primary 需管线；M-2 为不含管线的下限带
    "N": ("epv_profit", 1, (0.85, 1.00), True),               # primary 需同业利润率；N-2 用自身峰值
    "P": ("backlog_annual_profit", 1, (0.90, 1.10), True),    # primary 需订单；P-2 为不含订单的下限带
}

# §6.5.2 A-2 带系数按质量分层分档（v1.30，OI-004）
A2_COEFS = {"L1": (0.90, 1.15), "L2": (0.85, 1.05), "L3": (0.80, 1.00)}

# §6.5.3 C → A 迁出判据（v1.30，OI-005），带 12%/15% 迟滞
# 阈值按近三年最低 ROE 分档：ROE 越高，价值中来自存量特许经营权的比重越大，
# PEG（不含资本效率）越早失效，故越早迁出 C。
C_TO_A_CAGR_BY_ROE = ((20.0, 0.15), (12.0, 0.12))   # (ROE 下限, CAGR 阈值)
C_TO_A_MIN_ROE = 12.0
C_TO_A_MIN_CASH_CONV = 0.8

RISK_FREE = 0.018          # 10Y 国债，初始校准；修订先改工作流 §6.5.4
COE_BANK = 0.018 + 0.095   # 银行 ERP 8.0%-11.0% 取中值
MAX_G = 0.035

# §6.5.2.1 锚与倍数的同期约束（v1.30）：远期利润锚必须配终值倍数。
# PE = 1/(r − g_终值)，r 按质量分层（风险越高要求回报越高）。
TERMINAL_R_BY_TIER = {"L1": 0.09, "L2": 0.10, "L3": 0.11}
TERMINAL_G = 0.03

# §6.5.4 中枢窗口结构断点检验（v1.32，OI-007）：近 5 年净利率中位与前 5 年中位
# 偏离 >50% 即判存在结构断点，窗口收缩到近 5 年——否则结构性成长会被当成周期波动。
STRUCTURAL_BREAK_THRESHOLD = 0.50
# §6.5.4 营收周期性判据（v1.38，结 OI-010）：以「近 10 年营收下降年占比」区分
# 结构性成长与周期摆动。中枢口径用当期营收缩放的前提是营收本身不强周期；对存储器、
# 煤炭这类价与量同向摆动的品种，当期（峰值）营收缩放等于只归一化了利润率、没归一化规模。
REVENUE_GROWTH_MAX_DOWN = 0.20     # 下降年占比 ≤20% → 结构性成长，用当期营收
REVENUE_CYCLE_MIN_DOWN = 0.30      # 下降年占比 ≥30% → 周期摆动，用跨周期营收中位
PEER_MULTIPLE_MIN_GROUP = 3      # 同业组最少家数
PEER_MULTIPLE_LEVELS = (3, 2)    # 只用三级/二级行业；退到一级会把整个板块当同业
AS_OF_YEAR = 2026                # 折现基准年（现值口径的 T0）
AS_OF_DATE = f"{AS_OF_YEAR}-12-31"   # 由 main() 按 --as-of 覆盖；决定哪些报告期算「已结束」

# §6.5.3 A-1 / K primary / 通用校验二（v1.34，结 OI-008）
# v1.35（结 OI-009）：单点要求回报 + 固定带系数，带宽交回带系数控制。
# 原「rate 区间 [8%−g, 6%−g]」使带宽恒为 2.0 倍，档位分辨力退化。
# A-1 折现率（v1.41）：**r 是折现率不是收益目标**。把 r 设成收益目标（如 20%）会让
# 几乎没有公司能过，等于永远不买；超额收益应来自「买价 < 内在价值」，不是抬高 r。
# 8.5% = 10Y 国债 1.8% + 股权风险溢价 6.7%，并经全池实证校准：34 家 A 类的现价隐含
# 折现率中位 8.1%、四分位 6.8%/9.6%，与 §6.6 早已写好的 A 档标准（≥12% 低估 /
# 8-12% 较低估 / 6-8% 中性 / 4-6% 较高估 / <4% 高估）几乎完全重合。
A1_REQUIRED_RETURN = 0.085
K_REQUIRED_RETURN = 0.065            # K   要求回报 = 10Y 国债 1.8% + 受监管长久期资产溢价 4.7%
# 永续增长上限：高分红成熟公司按定义把大部分利润分掉，留存不足以支撑更高的永续增长。
# 2.5% 对应「长期通胀 + 极低实际增长」，即公司长期存在但不再扩张，低于 §6.5.4 的通用
# 3.5% 上限。**它不是收益率目标**——Gordon 的 g 是终局增长假设，取高会让分母塌陷。
PERPETUAL_G_CAP = 0.025
# §6.5.3 两阶段 DCF 交叉校验（v1.40）：单阶段 Gordon 在 g 逼近 r 时发散，所以 A-1 被
# 「可持续内生增长 ≤2.5%」挡在门外——代价是**所有还在增长的公司都没有绝对法对照**，
# 只剩自身历史 PE 中位这一相对法。相对法按构造无法发现系统性错价：若市场长期给低
# 估值，中位数就把这个低估值当成"合理"。两阶段 DCF 消除该盲区，并反解隐含折现率。
DCF_STAGE1_YEARS = 10
DCF_PERCENTILE_EXTREME = (15.0, 85.0)   # 现 PE 分位落在两端 → 倍数锚在另一个估值制度里
A1_A2_DIVERGENCE = 0.25              # 双口径中值偏离 >25% 置 band_fragile（§6.5.3）
A1_MIN_PAYOUT = 0.60                 # A-1 参与定带的分红率门槛（辅条件）
GORDON_MIN_SPREAD = 0.015            # Gordon 分母下限：g 必须 ≤ r − 1.5pp，否则模型发散
DIVIDENDS_PATH = ROOT / "data/interim/a_share_dividends.csv"
# §6.5.4 人工重估结论（v1.42）：业务趋势检验只能机械判「有没有连续单向变化」，
# 判不了「这个变化是否不可逆」——后者要看幅度、要看一致预期是否确认。逐票判定的
# 结论落在此文件，供建带引擎读取，使人工判断可复算、可审计，而不是散在正文里。
MANUAL_REVALUATION = ROOT / "data/interim/manual_revaluation_2026-08-01.csv"

# §6.5.7 逐票估值档案（v1.47，用户决定）：通用十类只作粗估，逐票精算落在档案里。
# `bespoke = true` 的行**完全脱离通用模型**——不跑 A/C/D/F/H/… 任何一条口径，
# 带只由档案给出。设立理由：紫金矿业在 F-2「取孰低」的 PE 腿与 PB 腿之间反复翻转，
# 连改五版仍不稳定；对这类公司继续套通用公式，只会按下葫芦起了瓢。
DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"
_DOSSIER_CACHE: dict[str, dict] | None = None


def dossier(code: str) -> dict | None:
    """逐票估值档案；`dossier_status != active` 的不生效。"""
    global _DOSSIER_CACHE
    if _DOSSIER_CACHE is None:
        _DOSSIER_CACHE = {}
        if DOSSIERS.exists():
            with DOSSIERS.open(encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    if (row.get("dossier_status") or "").strip() == "active":
                        _DOSSIER_CACHE[row["security_code"].zfill(6)] = row
    return _DOSSIER_CACHE.get(code)

# §6.5.4 运行率硬校验（v1.36，OI-001 的原始第 5 条，此前只写在文档、引擎实现 0 次）
RUN_RATE_FLOOR = 0.85            # 锚 < TTM 归母 × 0.85 即触发周期假设标记
# §6.5.4 超额利润持续年数（v1.38，结 OI-011）：把「周期顶 vs 结构性变化」的二选一，
# 换成一个连续量——超额利润还能持续几年。用户原述：「高利润持续的时间可能会比较长，
# 但也肯定不是无限期，取决于技术门槛以及新玩家是否大幅扩产」。
# 价值 = Σ(t=1..N) 运行率利润/(1+r)^t + 中枢利润 × 终值PE /(1+r)^N
EXCESS_YEARS_LADDER = (0, 2, 4, 6)      # 敏感度阶梯


_MANUAL_CACHE: dict[str, dict] = {}


def manual_verdict(code: str) -> dict | None:
    """逐票人工重估结论。`pe_median_usable`: yes 可沿用历史 PE 中位／no 不可信／watch 维持但标脆弱。"""
    if not _MANUAL_CACHE and MANUAL_REVALUATION.exists():
        with MANUAL_REVALUATION.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                _MANUAL_CACHE[row["security_code"].zfill(6)] = row
        _MANUAL_CACHE.setdefault("__loaded__", {})
    return _MANUAL_CACHE.get(code)


_DIVIDEND_CACHE: dict[str, dict] = {}


def shareholder_return(code: str) -> dict | None:
    """最近一个**完整年度**的现金分红总额与回购注销率（§6.5.3，OI-008）。

    只取含年报分配的年份——当年只有中期分配的行是部分年度，直接当年度分红会低估
    （判例：宁德时代 2026 行仅 65.3 亿 vs 2025 全年 363.4 亿）。
    """
    if not _DIVIDEND_CACHE:
        if DIVIDENDS_PATH.exists():
            with DIVIDENDS_PATH.open(encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    if row.get("has_annual") != "true" or not row.get("cash_dividend_total"):
                        continue
                    key = row["security_code"].zfill(6)
                    prior = _DIVIDEND_CACHE.get(key)
                    if prior is None or row["report_year"] > prior["report_year"]:
                        _DIVIDEND_CACHE[key] = row
        _DIVIDEND_CACHE.setdefault("__loaded__", {"report_year": ""})
    row = _DIVIDEND_CACHE.get(code)
    if not row or not row.get("cash_dividend_total"):
        return None
    cash = float(row["cash_dividend_total"])
    cancel = float(row.get("buyback_cancel_rate") or 0)
    return {"cash": cash, "cancel_rate": cancel, "year": row["report_year"]}


_PEER_CACHE: dict[str, tuple[dict[str, str], dict[str, float]]] = {}


def _peer_universe() -> tuple[dict[str, str], dict[str, float]]:
    """行业映射 + 各票自身 5 年 PE 中位（同业中枢倍数的样本池）。"""
    if "data" in _PEER_CACHE:
        return _PEER_CACHE["data"]
    industries: dict[str, str] = {}
    profiles = ROOT / "data/interim/a_share_company_profiles.csv"
    if profiles.exists():
        with profiles.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                code = row.get("security_code") or row.get("\ufeffsecurity_code")
                if code:
                    industries[code] = row.get("eastmoney_industry", "") or ""
    medians: dict[str, float] = {}
    for path in EVIDENCE_DIR.glob("*.json"):
        try:
            band = (json.loads(path.read_text(encoding="utf-8")).get("valuation_band") or {})
        except Exception:
            continue
        value = band.get("pe_ttm_median")
        if value and 0 < value < 200:      # 剔除亏损年造成的极端 PE
            medians[path.stem] = float(value)
    _PEER_CACHE["data"] = (industries, medians)
    return _PEER_CACHE["data"]


def consensus_revision(evidence: dict, year_offset: int = 0) -> tuple[str, float | None, int]:
    """一致预期的**修正方向**（v1.42，用户指令）——研报在上调还是下调。

    财务数据滞后、研报前瞻，但研报对周期股有顺周期外推的通病（§6.3.5）。修正方向是
    对这一通病的安全阀：上调说明周期未见顶，下调是最早的转向信号。
    做法：把同一预测年的研报按发布日排序、对半分，比较较新半数与较旧半数的归母中位数。
    """
    detail = (evidence.get("profit_forecast") or {}).get("ycmx") or []
    stats = (evidence.get("profit_forecast") or {}).get("yctj_list") or []
    years = sorted({int(r["YEAR"]) for r in stats if r.get("YEAR_MARK") == "E"})
    if not years:
        return "", None, 0
    target = years[min(year_offset, len(years) - 1)]
    points = []
    for report in detail:
        for slot in (1, 2, 3, 4):
            if (report.get(f"YEAR{slot}") == target and report.get(f"YEAR_MARK{slot}") == "E"
                    and report.get(f"PARENT_NETPROFIT{slot}") and report.get("PUBLISH_DATE")):
                points.append((report["PUBLISH_DATE"][:10], float(report[f"PARENT_NETPROFIT{slot}"])))
    if len(points) < 4:
        return "覆盖不足", None, len(points)
    points.sort()
    half = len(points) // 2
    older = statistics.median(v for _, v in points[:half])
    newer = statistics.median(v for _, v in points[half:])
    if older <= 0:
        return "不可算", None, len(points)
    change = newer / older - 1
    return ("上调" if change > 0.01 else "下调" if change < -0.01 else "持平"), change, len(points)


def business_trend_test(evidence: dict) -> tuple[str, str]:
    """业务是否存在**不可逆的劣化/优化**（v1.41，用户指令）。

    用于判断「自身历史 PE 中位」还能不能用作倍数锚：
    · 现 PE 处低位极端 + **无劣化** → 低估值是情绪而非基本面，历史 PE 趋势可参考；
      有劣化 → 低估值反映真实恶化，历史中位不可信，须人工重估。
    · 现 PE 处高位极端 + **无优化** → 高估值不可持续，历史 PE 趋势可参考；
      有优化 → 重估可能是结构性的，历史中位偏低，须人工重估。

    判据全部取自可机械核对的财务趋势（净利率、ROE、营收、现金转化），不含主观项；
    市占率与竞争格局无结构化数据源，须人工补（写入 note）。
    """
    rows = annual_rows(evidence.get("finance_periods") or [])[:4]
    if len(rows) < 4:
        return "", "年报期数不足 4 年，趋势不可判"

    def series(field: str) -> list[float]:
        return [float(r[field]) for r in rows if r.get(field) is not None]

    margins, roes = series("XSJLL"), series("ROEJQ")
    revenues = series("TOTALOPERATEREVE")
    cash_ratios = series("JYXJLYYSR")
    bad, good = [], []
    if len(margins) >= 3:
        if margins[0] < margins[1] < margins[2]:
            bad.append(f"净利率连续 3 年下降（{margins[2]:.1f}%→{margins[0]:.1f}%）")
        if margins[0] > margins[1] > margins[2]:
            good.append(f"净利率连续 3 年上升（{margins[2]:.1f}%→{margins[0]:.1f}%）")
    if len(roes) >= 3:
        if roes[0] < roes[1] < roes[2]:
            bad.append(f"ROE 连续 3 年下降（{roes[2]:.1f}%→{roes[0]:.1f}%）")
        if roes[0] > roes[1] > roes[2]:
            good.append(f"ROE 连续 3 年上升（{roes[2]:.1f}%→{roes[0]:.1f}%）")
    if len(revenues) >= 3 and revenues[0] < revenues[1] < revenues[2]:
        bad.append("营收连续 3 年下降")
    if len(cash_ratios) >= 3 and cash_ratios[0] < cash_ratios[1] < cash_ratios[2] and cash_ratios[0] < 0.05:
        bad.append("经营现金流/营收连续 3 年下降且低于 5%")
    if bad:
        return "劣化", "；".join(bad)
    if good:
        return "优化", "；".join(good)
    return "无明显趋势", "净利率/ROE/营收/现金转化均未见连续 3 年单向变化"


def two_stage_dcf(cash: float, g1: float, g2: float, rate: float, years: int = DCF_STAGE1_YEARS) -> float:
    """两阶段 DCF：N 年按可持续内生增长 g1，其后按永续 g2。"""
    if rate <= g2:
        return 0.0
    stage1 = sum(cash * (1 + g1) ** t / (1 + rate) ** t for t in range(1, years + 1))
    terminal = cash * (1 + g1) ** years * (1 + g2) / (rate - g2) / (1 + rate) ** years
    return stage1 + terminal


def implied_discount_rate(market_cap: float, cash: float, g1: float, g2: float) -> float | None:
    """从现价反解隐含折现率——「市场要求这家公司给多少年化回报」。

    比「相对历史中位贵/便宜」有用得多：它是一个可以直接和你的机会成本比较的数。
    """
    if market_cap <= 0 or cash <= 0:
        return None
    for step in range(1, 400):
        rate = g2 + 0.0005 * step
        if rate <= g2 + 0.001:
            continue
        if two_stage_dcf(cash, g1, g2, rate) <= market_cap:
            return round(rate, 4)
    return None


def excess_profit_value(run_rate: float, mid_cycle: float, years: int,
                        rate: float, terminal_pe: float) -> float:
    """中枢价值 + N 年**超额**利润现值（§6.5.4，OI-011）。

    `价值 = 中枢利润 × 终值PE + Σ(t=1..N) (运行率 − 中枢) / (1+r)^t`

    超额是 `运行率 − 中枢`，不是运行率本身；终值是从当下起算的永续，不再按 N 折现——
    首版两处都写错（把全部利润当超额、又对终值二次折现），结果价值随 N 反而下降。
    """
    base = mid_cycle * terminal_pe
    excess = max(0.0, run_rate - mid_cycle)
    return base + sum(excess / (1 + rate) ** t for t in range(1, years + 1))


def implied_excess_years(market_cap: float, run_rate: float, mid_cycle: float,
                         rate: float, terminal_pe: float, ladder_max: int = 20) -> float | None:
    """从现价**反解**市场隐含的超额利润年数。

    这比「模型说贵/便宜」有用得多：它把结论翻译成一句可以被供给侧证据检验的话——
    「市场在为 N 年的超额利润定价」，而 N 能不能成立取决于扩产周期、技术门槛、
    新进入者（长鑫/长江存储一类）的产能规划，那是可以去查证的事实。
    """
    if run_rate <= 0 or mid_cycle <= 0 or terminal_pe <= 0 or run_rate <= mid_cycle:
        return None
    low = excess_profit_value(run_rate, mid_cycle, 0, rate, terminal_pe)
    if market_cap <= low:
        return 0.0
    prior = low
    for n in range(1, ladder_max + 1):
        value = excess_profit_value(run_rate, mid_cycle, n, rate, terminal_pe)
        if market_cap <= value:
            span = value - prior
            return round(n - 1 + (market_cap - prior) / span, 1) if span > 0 else float(n)
        prior = value
    return None      # 即使 ladder_max 年超额也接不上现价 → 分歧不在持续年数，在中枢水平本身


def latest_quarter_annualized(periods: list[dict], field: str = "PARENTNETPROFIT") -> tuple[float | None, str]:
    """最近一个已披露季度的**年化运行率**（单季 × 4）。

    §6.5.4：`峰值/中枢盈利输入不得低于最近一个已披露季度的年化运行率`。该条是 OI-001
    为美光判例写的，但此前**只存在于文档、引擎实现 0 次**——直接后果是本轮把美光判成
    「量级错误」（真相：FY2026Q3 单季净利 $28.24B，年化 $113B，前瞻 EPS $150 完全成立），
    并在 A 股产出 13 行锚低于运行率的结论（紫金矿业锚/运行率仅 0.42）。
    """
    rows = [p for p in periods if p.get(field) is not None]
    rows.sort(key=lambda p: p["REPORT_DATE"], reverse=True)
    by_date = {p["REPORT_DATE"][:10]: p for p in rows}
    order = ["03-31", "06-30", "09-30", "12-31"]
    for period in rows:
        date = period["REPORT_DATE"][:10]
        year, mmdd = date[:4], date[5:10]
        if mmdd not in order:
            continue
        idx = order.index(mmdd)
        current = float(period[field])
        if idx == 0:
            return current * 4, date
        prior = by_date.get(f"{year}-{order[idx - 1]}")
        if prior is not None and prior.get(field) is not None:
            return (current - float(prior[field])) * 4, date
    return None, ""


def deducted_pe_median(evidence: dict, pe_median: float | None) -> tuple[float | None, str]:
    """把**归母口径**的 PE 中位换算成**扣非口径**（v1.33）。

    数据源的 `pe_ttm_median` = 市值 ÷ 归母TTM，而 A-2/E/K-2 的锚是**扣非归母**。
    两者口径不同，直接相乘会系统性低估：扣非 < 归母，低估幅度即 (1 − 扣非/归母)。
    实测美的集团 6.1%、宁德时代 11.0%、东阿阿胶 8.1%（茅台 1.00 无影响）。

    换算：`PE扣非中位 = PE归母中位 ÷ 历史(扣非/归母)中位`。
    """
    if not pe_median:
        return None, ""
    ratios = []
    for row in annual_rows(evidence.get("finance_periods") or [])[:8]:
        deducted, parent = row.get("KCFJCXSYJLR"), row.get("PARENTNETPROFIT")
        if deducted and parent and float(parent) > 0:
            ratios.append(float(deducted) / float(parent))
    if not ratios:
        return pe_median, "（无扣非/归母历史，未作口径换算）"
    ratio = statistics.median(ratios)
    if not 0.3 < ratio < 1.5:
        return pe_median, f"（扣非/归母中位 {ratio:.3f} 异常，未换算）"
    return round(pe_median / ratio, 2), f"（已按历史扣非/归母中位 {ratio:.3f} 换算为扣非口径）"


def peer_multiple(code: str) -> tuple[float | None, str]:
    """§6.5.4（v1.32，OI-006）：同业中枢 PE = 同业各票「自身 5 年 PE 中位」的中位数。

    只用三级/二级行业分组且组内 ≥3 家。退到一级会把整个板块当同业——判例：
    紫金矿业退到「有色金属」16 家得 29.6x（混入锂/稀土），京东方退到「电子设备」
    55 家得 48.8x，两者对各自细分行业都无意义。
    """
    industries, medians = _peer_universe()
    own = industries.get(code, "")
    if not own:
        return None, ""
    for level in PEER_MULTIPLE_LEVELS:
        key = "-".join(own.split("-")[:level])
        peers = [v for c, v in medians.items()
                 if c != code and "-".join(industries.get(c, "").split("-")[:level]) == key
                 and industries.get(c)]
        if len(peers) >= PEER_MULTIPLE_MIN_GROUP:
            trimmed = sorted(peers)[1:-1] if len(peers) >= 5 else sorted(peers)
            return round(statistics.median(trimmed), 2), f"{key}（{len(peers)} 家同业，{level} 级）"
    return None, ""


def load_evidence(code: str) -> dict | None:
    path = EVIDENCE_DIR / f"{code}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def annual_rows(periods: list[dict]) -> list[dict]:
    """年报行，按报告期倒序。合成的预告/快报行不带 `年报` 标签，天然不入本函数。"""
    return [p for p in periods if p.get("REPORT_TYPE") == "年报"]


# §6.5.2.2（v1.46，结 OI-015 第 1 条，用户指令「对所有公司，都将业绩预告包含在业绩报告的范畴中」）
FORECAST_FIELD_BY_CODE = {"004": "PARENTNETPROFIT", "005": "KCFJCXSYJLR", "008": "TOTALOPERATEREVE"}
FORECAST_GROWTH_CODES = {"001": "TOTALOPERATEREVE", "006": "TOTALOPERATEREVE"}
FORECAST_MIN_ELAPSED = 0.5       # 公告日时报告期至少走完一半，否则算预测不算业绩


def _period_start(period_end: str) -> str:
    """报告期起点：A 股定期报告一律自然年内累计，故起点恒为当年 1 月 1 日。"""
    return f"{period_end[:4]}-01-01"


def _elapsed_fraction(period_end: str, notice: str) -> float:
    """公告日时该报告期已走完的比例。>1 表示期末之后才公告（绝大多数情形）。"""
    start, end, nd = _period_start(period_end), datetime.date.fromisoformat(period_end), None
    try:
        nd = datetime.date.fromisoformat(notice)
    except ValueError:
        return 0.0
    s = datetime.date.fromisoformat(start)
    span = (end - s).days or 1
    return (nd - s).days / span


def forecast_periods(evidence: dict, as_of: str) -> list[dict]:
    """把**尚无定期报告**的报告期，按业绩快报/业绩预告合成为期数行。

    §6.5.4 的运行率硬校验与各类 TTM 锚此前只读 `finance_periods`，预告与快报从不入参。
    直接后果（OI-015 判例高德红外）：锚为 2026Q1 口径 TTM 扣非 9.04 亿，而 7/9 预告的
    H1'26 扣非已达 12.35-14.15 亿——单个半年即超过全部 TTM——运行率比值按 0.93 通过
    0.85 阈值，真实比值 0.48。

    **取舍的分界线是「有没有对应的定期报告」，不是「报告期结不结束」**（v1.46 修订）：
    定期报告一旦披露，同期预告/快报即刻作废、直接丢弃（实测全池 1005 行预告属此类）；
    真正有价值的恰恰是**还没有定期报告的那一期**（实测 155 行）。报告期是否已过期末
    只是个次要的可靠性指标——A 股预告最早可提前 77 天发布（中位提前 36 天），届时
    报告期已走完大半，把它一律当「预测」丢掉会让锚白白落后一整期。

    三道门（须全部满足）：
      ① **未被定期报告取代**：`REPORT_DATE` 必须晚于最新已披露定期报告期；
      ② **披露已发生**：`NOTICE_DATE ≤ as_of`——回放口径，不得使用当日尚未公告的信息
         （此前误用 `REPORT_DATE ≤ as_of`，会把「期未结束但已公告」的预告错误排除）；
      ③ **报告期已实质走完**：公告日时该期已过 ≥50%，否则属真预测，走一致预期口径。

    取值：**区间中值**（v1.46 改，原取下限）。实测全池 1063 条盈利预告的相对区间宽度
    中位仅 **9.8%**、P90 22.2%、>50% 的仅 1 条——区间很窄，参考价值高；取下限等于给
    锚加一道约 5% 的**系统性下偏**，而安全边际本就由带系数承担（v1.33 已否决过同类
    二次保守）。这与一致预期取中位数是同一原则。
    """
    periods = evidence.get("finance_periods") or []
    latest = max((p["REPORT_DATE"][:10] for p in periods
                  if p.get("PARENTNETPROFIT") is not None), default="")
    rows: dict[str, dict] = {}

    def admissible(date: str, notice: str) -> bool:
        return bool(date) and date > latest and bool(notice) and notice <= as_of \
            and _elapsed_fraction(date, notice) >= FORECAST_MIN_ELAPSED

    def mid(lo, hi):
        """区间中值；单边给出时取给出的那一边。"""
        vals = [float(v) for v in (lo, hi) if v is not None]
        return sum(vals) / len(vals) if vals else None

    for item in (evidence.get("performance_predicts") or []):
        date, notice = str(item.get("REPORT_DATE") or "")[:10], str(item.get("NOTICE_DATE") or "")[:10]
        if not admissible(date, notice):
            continue
        code = item.get("PREDICT_FINANCE_CODE")
        row = rows.setdefault(date, {"REPORT_DATE": date, "REPORT_TYPE": "业绩预告",
                                     "_forecast_notice": notice,
                                     "_forecast_elapsed": _elapsed_fraction(date, notice)})
        if code in FORECAST_FIELD_BY_CODE:
            value = mid(item.get("PREDICT_AMT_LOWER"), item.get("PREDICT_AMT_UPPER"))
            if value is not None:
                row[FORECAST_FIELD_BY_CODE[code]] = value
        elif code in FORECAST_GROWTH_CODES:
            # 营收类预告多数只给增速（全池 134 条营收预告中 129 条是 006 增速式），
            # 按同期上年累计还原绝对额；增速同样取区间中值。
            rate = mid(item.get("ADD_AMP_LOWER"), item.get("ADD_AMP_UPPER"))
            prior = next((p.get(FORECAST_GROWTH_CODES[code]) for p in periods
                          if p["REPORT_DATE"][:10] == f"{int(date[:4]) - 1}{date[4:]}"), None)
            if rate is not None and prior:
                row[FORECAST_GROWTH_CODES[code]] = float(prior) * (1 + rate / 100)

    for item in (evidence.get("performance_express") or []):
        date, notice = str(item.get("REPORT_DATE") or "")[:10], str(item.get("NOTICE_DATE") or "")[:10]
        if not admissible(date, notice):
            continue
        # 快报覆盖同期预告：数值更接近终值。快报无扣非，该字段由同期预告补。
        row = {"REPORT_DATE": date, "REPORT_TYPE": "业绩快报", "_forecast_notice": notice,
               "_forecast_elapsed": _elapsed_fraction(date, notice)}
        if item.get("PARENT_NETPROFIT") is not None:
            row["PARENTNETPROFIT"] = float(item["PARENT_NETPROFIT"])
        if item.get("TOTAL_OPERATE_INCOME") is not None:
            row["TOTALOPERATEREVE"] = float(item["TOTAL_OPERATE_INCOME"])
        if len(row) > 4:
            prior = rows.get(date) or {}
            if prior.get("KCFJCXSYJLR") is not None:
                row["KCFJCXSYJLR"] = prior["KCFJCXSYJLR"]
            rows[date] = row

    return sorted(rows.values(), key=lambda r: r["REPORT_DATE"], reverse=True)


def augmented_periods(evidence: dict, as_of: str) -> list[dict]:
    """已披露期数 + 合成的预告/快报期数（§6.5.2.2）。"""
    return forecast_periods(evidence, as_of) + (evidence.get("finance_periods") or [])


def forecast_note(periods: list[dict], field: str) -> str:
    """本字段的 TTM 若用到了预告/快报期，返回可审计的说明；否则空串。"""
    rows = [p for p in periods if p.get(field) is not None]
    if not rows:
        return ""
    newest = max(rows, key=lambda p: p["REPORT_DATE"])
    if not newest.get("_forecast_notice"):
        return ""
    elapsed = newest.get("_forecast_elapsed") or 0
    basis = "取区间中值" if newest.get("REPORT_TYPE") == "业绩预告" else "快报值"
    return (f"（含 {newest['REPORT_DATE'][:10]} {newest.get('REPORT_TYPE')}，"
            f"公告 {newest['_forecast_notice']}，公告时该期已过 {min(elapsed, 1):.0%}，{basis}）")


def ttm(periods: list[dict], field: str) -> float | None:
    """§6.5.2.1 取数陷阱一：finance_periods 是累计口径，须差分成单季再求 TTM。

    单季 = 本期累计 − 同年上期累计（一季报本身即单季）。TTM = 最近四个单季之和。

    §6.5.2.2 同口径保护：预告只给利润、不给营收是常态（实测 74 家有预告、仅 11 家
    带营收）。若最新的合成期缺本字段，则本次调用**整体退回已披露期数**——同一个
    字段的 TTM 绝不半新半旧。跨字段的同口径由 `ttm_same_vintage()` 单独保证。
    """
    if any(p.get("_forecast_notice") for p in periods):
        newest = max(periods, key=lambda p: p["REPORT_DATE"])
        if newest.get("_forecast_notice") and newest.get(field) is None:
            periods = [p for p in periods if not p.get("_forecast_notice")]
    rows = [p for p in periods if p.get(field) is not None]
    rows.sort(key=lambda p: p["REPORT_DATE"], reverse=True)
    by_date = {p["REPORT_DATE"][:10]: p for p in rows}

    def quarter_value(period: dict) -> float | None:
        date = period["REPORT_DATE"][:10]
        year, mmdd = date[:4], date[5:10]
        order = ["03-31", "06-30", "09-30", "12-31"]
        if mmdd not in order:
            return None
        idx = order.index(mmdd)
        cur = period.get(field)
        if cur is None:
            return None
        if idx == 0:
            return float(cur)
        prev = by_date.get(f"{year}-{order[idx - 1]}")
        if prev is None or prev.get(field) is None:
            return None
        return float(cur) - float(prev[field])

    quarters = []
    for period in rows:
        value = quarter_value(period)
        if value is not None:
            quarters.append(value)
        if len(quarters) == 4:
            return sum(quarters)
    # 兜底：**年报 + 本年累计 − 上年同期累计**（v1.58）。
    # 四单季差分要求四个季度连续可得，中间缺任一期即整体失败——次新股尤其常见：
    # 盛合晶微 2025 年上市，`finance_periods` 无 2025 三季报，TTM 因此返回 None，
    # 而它 FY2025 归母 9.21亿、Q1'26 1.91亿，TTM 明明可算（9.21+1.91−1.26 = 9.86亿）。
    # 该判例由 §15.2 第 3 条的列覆盖自检（无 TTM 行清单）抓出。
    annual = {p["REPORT_DATE"][:10]: p for p in rows if p["REPORT_DATE"][5:10] == "12-31"}
    ytd = [p for p in rows if p["REPORT_DATE"][5:10] != "12-31"]
    if annual and ytd:
        latest = max(ytd, key=lambda p: p["REPORT_DATE"])
        year, mmdd = latest["REPORT_DATE"][:4], latest["REPORT_DATE"][5:10]
        prior_annual = annual.get(f"{int(year) - 1}-12-31")
        prior_ytd = by_date.get(f"{int(year) - 1}-{mmdd}")
        if prior_annual and prior_ytd and prior_annual.get(field) is not None and prior_ytd.get(field) is not None:
            return float(prior_annual[field]) + float(latest[field]) - float(prior_ytd[field])
    return None


def reported_only(periods: list[dict]) -> list[dict]:
    """剔除合成的预告/快报期。分红率一类以**已披露年度**为分子的比值必须用它当分母，
    否则分子停在上一年报、分母已滚入预告，分红率会被机械压低（§6.5.2.2）。"""
    return [p for p in periods if not p.get("_forecast_notice")]


def ttm_same_vintage(periods: list[dict], *fields: str) -> tuple[float | None, ...]:
    """多个字段的 TTM，强制**同一口径批次**（§6.5.2.2）。

    专供跨字段相除的场合——净利率 = 利润 ÷ 营收、现金转化 = 经营现金 ÷ 利润。
    预告普遍只给利润不给营收（74 家有预告、仅 11 家带营收），若利润取到预告口径
    而营收停在已披露口径，得到的净利率会被机械抬高，再乘回营收就放大成带的虚高。
    故只要有任一字段在最新合成期缺失，全部字段一起退回已披露期数。
    """
    if any(p.get("_forecast_notice") for p in periods):
        newest = max(periods, key=lambda p: p["REPORT_DATE"])
        if newest.get("_forecast_notice") and any(newest.get(f) is None for f in fields):
            periods = [p for p in periods if not p.get("_forecast_notice")]
    return tuple(ttm(periods, f) for f in fields)


def consensus_median(evidence: dict, year_offset: int = 0) -> tuple[float | None, int, int | None]:
    """§6.5.2.1 取数陷阱二：一致预期取 ycmx 逐份研报归母的**中位数**，不用 yctj_list 均值。

    Returns (归母中位数(元), 覆盖机构数, 预测年份).
    """
    detail = (evidence.get("profit_forecast") or {}).get("ycmx") or []
    stats = (evidence.get("profit_forecast") or {}).get("yctj_list") or []
    forecast_years = sorted({int(r["YEAR"]) for r in stats if r.get("YEAR_MARK") == "E"})
    if not forecast_years:
        return None, 0, None
    idx = min(year_offset, len(forecast_years) - 1)
    target = forecast_years[idx]

    values = []
    for report in detail:
        for slot in (1, 2, 3, 4):
            if report.get(f"YEAR{slot}") == target and report.get(f"YEAR_MARK{slot}") == "E":
                value = report.get(f"PARENT_NETPROFIT{slot}")
                if value:
                    values.append(float(value))
    if not values:
        return None, 0, target
    return statistics.median(values), len(values), target


def best_consensus(evidence: dict, offsets: tuple[int, ...], min_coverage: int = 3):
    """在给定的预测年偏移中，取**覆盖达标的最远年份**。

    §6.5.2 D 类的锚是"未来 2-3 年正常化归母"——硬取第 3 年会在覆盖薄的中小盘上
    整片落空，而第 2 年同样落在标准区间内。返回 (归母中位数, 覆盖数, 年份)；
    全部不达标返回 (None, 0, None)。
    """
    for offset in offsets:
        value, count, year = consensus_median(evidence, offset)
        if value and count >= min_coverage:
            return value, count, year
    return None, 0, None


def share_count_check(evidence: dict, shares_out: float | None) -> str:
    """§6.6.1.2a 股本口径校验：研报归母 ÷ 研报 EPS 反算隐含股本，与现股本比对。"""
    detail = (evidence.get("profit_forecast") or {}).get("ycmx") or []
    implied = []
    for report in detail:
        for slot in (1, 2, 3, 4):
            eps, profit = report.get(f"EPS{slot}"), report.get(f"PARENT_NETPROFIT{slot}")
            if eps and profit and float(eps) != 0:
                implied.append(float(profit) / float(eps) / 1e8)
    if not implied or not shares_out:
        return "无法校验（缺研报 EPS 或股本）"
    med = statistics.median(implied)
    ratio = med / shares_out
    if abs(ratio - 1) <= 0.02:
        return f"通过（隐含股本 {med:.4f}亿 ≈ 现股本 {shares_out:.4f}亿）"
    return (f"⚠️不一致（隐含 {med:.4f}亿 vs 现 {shares_out:.4f}亿，比值 {ratio:.3f}）"
            f"——研报 EPS 为送转/增发前口径，一律用归母建带")


def c_to_a_signal(evidence: dict) -> tuple[bool, str]:
    """§6.5.3 C → A 迁出判据（v1.30）：三条须全部成立。

    ① 三年一致预期归母 CAGR < 12%  ② 近三年 ROE 均 ≥ 12%  ③ 经营现金流/净利润 ≥ 0.8
    只满足 ① 的不迁 A——那是质量下滑，须回 §6.5.0 重走判定顺序。
    「连续两次复核」由估值执行侧跨轮判断，本函数只给单轮读数。
    """
    profits = [consensus_median(evidence, i)[0] for i in range(3)]
    if not all(profits) or profits[0] <= 0:
        return False, "增速不可算"
    cagr = (profits[-1] / profits[0]) ** 0.5 - 1

    rows = annual_rows(evidence.get("finance_periods") or [])[:3]
    roes = [float(r["ROEJQ"]) for r in rows if r.get("ROEJQ") is not None]
    # §6.5.2.1 取数陷阱三：JYXJLYYSR 是**小数比率**（0.3644 = 36.44%），
    # 与同记录内的 XSJLL/ROEJQ（百分数）单位不同，不得再除以 100。
    ratios = [float(r["JYXJLYYSR"]) for r in rows if r.get("JYXJLYYSR") is not None]
    # 现金转化是跨字段相除，须同口径（§6.5.2.2）
    revenue, profit_ttm = ttm_same_vintage(
        augmented_periods(evidence, AS_OF_DATE), "TOTALOPERATEREVE", "PARENTNETPROFIT")
    cash_conv = None
    if ratios and revenue and profit_ttm and profit_ttm > 0:
        cash_conv = (statistics.median(ratios) * revenue) / profit_ttm

    min_roe = min(roes) if len(roes) >= 3 else None
    threshold = next((t for floor, t in C_TO_A_CAGR_BY_ROE if min_roe is not None and min_roe >= floor), None)
    cond1 = threshold is not None and cagr < threshold
    cond2 = min_roe is not None and min_roe >= C_TO_A_MIN_ROE
    cond3 = cash_conv is not None and cash_conv >= C_TO_A_MIN_CASH_CONV
    threshold_text = f"<{threshold:.0%}" if threshold is not None else "本判据不适用（ROE<12%）"
    roe_text = f"{min_roe:.1f}%" if min_roe is not None else "不可算"
    detail = (f"三年一致预期 CAGR {cagr:.1%}（判据① {threshold_text} {'✓' if cond1 else '✗'}"
              f"，阈值按近三年最低 ROE {roe_text} 分档）；"
              f"近三年 ROE {'/'.join(f'{r:.1f}' for r in roes[:3])}（②均≥12% {'✓' if cond2 else '✗'}）；"
              f"经营现金流/净利润 {cash_conv:.2f}（③≥0.8 {'✓' if cond3 else '✗'}）"
              if cash_conv is not None else
              f"三年一致预期 CAGR {cagr:.1%}；现金转化不可算")
    return (cond1 and cond2 and cond3), detail


def forward_present_value(code: str, anchor: float, year: int | None, as_of_year: int,
                          rate: float | None, terminal_pe: float | None) -> tuple[float | None, str]:
    """远期利润锚 → **现值**（v1.32，结 OI-006）。

    `PV = E(T+n) × PE终值 ÷ (1+r)^n`。两处纠正：

    1. **必须折现**。`E(T+n) × PE` 得到的是 T+n 时点的价值，不是现值；v1.30/v1.31
       漏了折现，等于把 2-3 年后的价格当成今天该付的价格。
    2. **倍数只能取终值口径**。自身历史 PE 中位嵌着当年的增长预期（v1.30 已认定），
       **同业历史 PE 中位嵌着同一个年代的行业增长预期，毛病完全相同**——判例：
       宁德时代同业中枢 33.77x 用在 2028E 归母上，隐含市值 4.8 万亿、为当时市值
       18289 亿的 2.6 倍。故同业中枢只作交叉校验写入敏感度，不作建带倍数。

    窗口之后的增长不进 base 带，按 §6.5.6 成长期权有界补入——这正是该机制存在的理由。
    """
    if not (rate and terminal_pe and anchor and year):
        return None, ""
    years = max(1, year - as_of_year)
    present = anchor * terminal_pe / (1 + rate) ** years
    peer, peer_note = peer_multiple(code)
    note = (f"终值 PE {terminal_pe}x = 1/({rate:.0%}−{TERMINAL_G:.0%})，"
            f"折现 {years} 年回现值（÷{(1 + rate) ** years:.3f}）"
            + (f"；交叉校验：同业中枢 PE {peer}x（{peer_note}），仅作对照不入带——"
               f"行业历史倍数同样嵌有当年的增长预期" if peer else ""))
    return present, note



def ttm_augmented_profit(evidence: dict, as_of: str) -> float | None:
    """已披露口径的 TTM 归母（含已结束报告期的预告/快报，§6.5.2.2）。"""
    return ttm(augmented_periods(evidence, as_of), "PARENTNETPROFIT")


def runrate_invariant(evidence: dict, as_of: str, anchor_earnings_yi: float | None) -> tuple[str, str]:
    """§6.5.4 运行率不变量（v1.52，结 OI-018）——**对每一条带生效，与锚的口径无关**。

    原实现把校验挂在 `anchor_scope == "market_cap"` 上，于是走 PB / DPS 路径的行
    从不进入校验；而逐票档案一律置 `per_share`，**每建一份档案就多一行脱离校验**
    ——OI-018 登记时 37 行，建档 31 家后升至 67 行，覆盖不增反减。校验本该挂在
    **事实**（带所依据的盈利 vs 已披露盈利）上，而不是挂在带由哪条路径产生上。

    锚不是盈利口径的（净资产锚、市销率锚）显式返回「不适用」而非静默跳过——
    静默跳过正是 §15.2 第 3 条点名的病。
    """
    t = ttm_augmented_profit(evidence, as_of)
    if not t or t <= 0:
        return "na_no_ttm", "运行率不变量：TTM 归母 ≤0 或不可算，不适用"
    ttm_yi = t / 1e8
    if anchor_earnings_yi is None:
        return "na_not_earnings", (f"运行率不变量：本档锚非盈利口径（净资产/市销率等），不适用；"
                                   f"对照已披露 TTM 归母 {ttm_yi:.2f}亿")
    ratio = anchor_earnings_yi / ttm_yi
    if ratio < RUN_RATE_FLOOR:
        return "below_runrate", (f"⚠运行率不变量触发：盈利锚 {anchor_earnings_yi:.2f}亿 仅为已披露 TTM 归母 "
                                 f"{ttm_yi:.2f}亿 的 {ratio:.2f} 倍（阈值 {RUN_RATE_FLOOR}）——"
                                 f"锚低于运行率须有明写理由（周期均值回归／一次性收益剔除），否则应上修")
    return "ok", f"运行率不变量：盈利锚 {anchor_earnings_yi:.2f}亿 ÷ 已披露 TTM 归母 {ttm_yi:.2f}亿 = {ratio:.2f}"


def build_card(code: str, name: str, tag_letter: str, quality_tier: str) -> dict:
    """建带卡。**运行率不变量在此统一兜底**（v1.53）——`_build_card` 有多个 return 分支，
    逐个挂校验必然漏（v1.52 首版即漏掉 K primary Gordon 分支的 4 行，苏泊尔/杭氧股份/
    长江电力/养元饮品 产出空的 `runrate_check`，属 §15.2 第 3 条的静默缺口）。
    改为在唯一出口统一补：任何分支未给出结论的，在这里按盈利锚重算一次。
    """
    card = _build_card(code, name, tag_letter, quality_tier)
    if not card.get("runrate_check"):
        evidence = load_evidence(code)
        if evidence is None:
            card["runrate_check"] = "na_no_evidence"
        else:
            scope = card.get("anchor_scope")
            try:
                anchor_yi = float(card.get("anchor_value") or "") if scope == "market_cap" else None
            except ValueError:
                anchor_yi = None
            card["runrate_check"], _ = runrate_invariant(evidence, AS_OF_DATE, anchor_yi)
    return card


def _build_card(code: str, name: str, tag_letter: str, quality_tier: str) -> dict:
    evidence = load_evidence(code)
    card = {
        "security_code": code,
        "security_name": name,
        "quality_tier": quality_tier,
        "strategy_tag_letter": tag_letter,
        "anchor_metric": "",
        "anchor_value": "",
        "anchor_scope": "",
        "anchor_basis": "",
        "multiple_or_rate": "",
        "multiple_source": "",
        "band_low_coef": "",
        "band_high_coef": "",
        "shares_out": "",
        "band_derivation": "model",
        "anchor_quality": "primary",
        "upgrade_path": "",
        "band_is_floor": "",
        "anchor_vintage": "",        # §6.5.2.2：锚是否用到已结束报告期的预告/快报
        "method_divergence": "",     # §6.5.3：双口径中值背离比例（OI-016 的卖出抑制依据）
        "runrate_check": "",         # §6.5.4 运行率不变量（v1.52，OI-018）
        "cycle_assumption": "",
        "scenario_band_low": "",
        "scenario_band_high": "",
        "cycle_note": "",
        "implied_excess_years": "",
        "excess_years_ladder": "",
        "cycle_gap_kind": "",
        "multiple_regime_flag": "",
        "implied_return": "",
        "implied_return_tier": "",
        "manual_verdict": "",
        "band_sensitivity": "",
        "band_fragile": "false",
        "fair_price_low": "",
        "fair_price_high": "",
        "needs_external": "",
        "note": "",
    }
    # §6.5.7（v1.47）：bespoke 档案**完全脱离通用模型**——在标签分派之前就返回，
    # 通用口径一条都不跑。用户决定：「对于反复处理不好的公司，标记为特殊公司，
    # 逐案例分析，不再使用相关行业的共用估值方法。」
    doc = dossier(code)
    if doc and str(doc.get("bespoke", "")).strip().lower() == "true":
        card.update(
            anchor_metric="dossier", anchor_scope="per_share", band_derivation="dossier",
            anchor_quality="primary", multiple_source="dossier",
            fair_price_low=doc.get("band_low", ""), fair_price_high=doc.get("band_high", ""),
            anchor_basis=f"逐票档案（§6.5.7，脱离通用模型）：{doc.get('band_method','')}。"
                         f"{doc.get('band_derivation','')}"[:1200],
            band_sensitivity=f"跟踪指标：{doc.get('key_metrics','')}｜复核触发：{doc.get('review_triggers','')}"
                             f"｜定案：{doc.get('decided_by','')}（{doc.get('reviewed_at','')}）",
            upgrade_path=doc.get("notes", "")[:400],
        )
        try:
            ae = float(doc.get("anchor_earnings_yi") or "")
        except ValueError:
            ae = None
        if evidence is not None:
            flag, note = runrate_invariant(evidence, AS_OF_DATE, ae)
            card["runrate_check"] = flag
            card["band_sensitivity"] = (card["band_sensitivity"] + "｜" + note)[:1600]
        return card

    spec = TYPE_SPEC.get(tag_letter)
    if spec is None:
        card["note"] = f"未知标签 {tag_letter}"
        return card
    anchor_metric, shape, coefs, local = spec
    if coefs is None:                                  # A-2：系数按质量分层（§6.5.2，v1.30）
        coefs = A2_COEFS.get(str(quality_tier).strip().upper())
        if coefs is None:
            card["note"] = f"A-2 需要 L1/L2/L3 分层定系数，实得 '{quality_tier}'"
            return card
    low_coef, high_coef = coefs
    card.update(anchor_metric=anchor_metric, band_low_coef=low_coef, band_high_coef=high_coef)

    if evidence is None:
        card["note"] = "缺证据文件"
        return card

    quote = evidence.get("quote") or {}
    price = quote.get("price")
    cap = quote.get("total_market_cap")
    shares = (cap / price / 1e8) if (price and cap) else None   # 亿股；比值与价格无关
    if shares:
        card["shares_out"] = f"{shares:.4f}"

    # §6.5.2.2（v1.45，结 OI-015）：已披露期数 + 已结束报告期的预告/快报。
    # 「业绩预告属于业绩报告」——一个已经结束的报告期的预告是已兑现盈利。
    periods = augmented_periods(evidence, AS_OF_DATE)
    band = evidence.get("valuation_band") or {}

    anchor = None
    basis = ""
    multiple = None
    source = ""

    # §6.5.3 通用校验二（v1.34 改双向，结 OI-008）——**只报不改带**。
    #
    # 先实现为「改带」版本（把带调到现金回报 = 要求回报的价格）并被实测否决：
    # 它等价于要求每家公司都给 6-8% 的**纯现金**回报，而成长公司按设计留存收益。
    # 231/261 行被改，贵州茅台带压到 755-965（现价 1205）、宁德时代压到 107-131
    # （现价 395）——显然不成立。要求回报对应的是「现金回报 + 增长」的**总回报**，
    # 不是现金回报本身。故改为：算总回报、写入敏感度、决定性背离时置 fragile，
    # 不重写带。适用范围按 §6.5.3 限 A/H/J/K（股东回报构成主要价值来源的四类）。
    def shareholder_return_check(low: float, high: float) -> tuple[float, float, str]:
        if tag_letter not in ("A", "H", "J", "K"):
            return low, high, ""
        sr_data = shareholder_return(code)
        if not (sr_data and shares and high > 0):
            return low, high, ""
        distributable = sr_data["cash"] + sr_data["cancel_rate"] * (quote.get("total_market_cap") or 0)
        if distributable <= 0:
            return low, high, ""
        # 分红为已披露年度口径，分母同口径（§6.5.2.2）
        profit = ttm(reported_only(periods), "PARENTNETPROFIT")
        payout = (sr_data["cash"] / profit) if (profit and profit > 0) else None
        roe_rows = [float(r["ROEJQ"]) for r in annuals[:3] if r.get("ROEJQ") is not None]
        growth = 0.0
        if roe_rows and payout is not None:
            growth = max(0.0, min(PERPETUAL_G_CAP, statistics.median(roe_rows) / 100 * (1 - min(payout, 1.0))))
        mid = (low + high) / 2
        cash_yield = distributable / (mid * shares * 1e8)
        total = cash_yield + growth
        r_low, r_high = A1_REQUIRED_RETURN - 0.01, A1_REQUIRED_RETURN + 0.01
        verdict = ("总回报高于要求区间，带偏保守" if total > r_high else
                   "总回报低于要求区间，带偏乐观" if total < r_low else "总回报落在要求区间内，带自洽")
        note = (f"通用校验二（{sr_data['year']}）：带中值处现金回报 {cash_yield:.2%}"
                f"（分红 {sr_data['cash']/1e8:.1f}亿 + 回购注销 {sr_data['cancel_rate']:.2%}）"
                f" + 内生增长 {growth:.2%} = 总回报 {total:.2%} vs 要求 [{r_low:.0%},{r_high:.0%}] — {verdict}")
        if total > r_high * 1.5 or total < r_low * 0.5:
            card["band_fragile"] = "true"
        return low, high, note

    tier_key = str(quality_tier).strip().upper()
    terminal_rate = TERMINAL_R_BY_TIER.get(tier_key)
    terminal_pe = round(1 / (terminal_rate - TERMINAL_G), 2) if terminal_rate else None
    pb_median = band.get("pb_median")
    current_pb = band.get("current_pb") or (quote.get("pb") if quote else None)
    bvps = (float(quote["price"]) / float(current_pb)) if (quote.get("price") and current_pb) else None
    annuals = annual_rows(periods)

    def mid_cycle_profit() -> tuple[float | None, str]:
        """§6.5.4（v1.32）：中枢归母 = TTM 营收 × 窗口净利率中位。

        规模取自**当期营收**、周期取自**历史利润率**——把结构性成长与周期波动分开。
        原「近 7 个年报归母算术均值」会把十年间的结构性扩张当成周期低点（紫金矿业
        判例：均值 216 亿 vs 规模口径 338 亿），且被单一重整年击穿（盐湖股份 −459 亿
        使均值为负）。中位数天然抗离群年，营收缩放天然吸收规模变化。
        """
        margins = [float(r["XSJLL"]) for r in annuals if r.get("XSJLL") is not None]
        # 净利率 = 利润 ÷ 营收，跨字段相除须同口径（§6.5.2.2）：预告普遍只给利润不给营收，
        # 若利润取预告口径而营收停在已披露口径，净利率会被机械抬高、再乘回营收放大成虚高的带。
        revenue, profit_ttm = ttm_same_vintage(periods, "TOTALOPERATEREVE", "PARENTNETPROFIT")
        revenue_ttm = revenue
        if len(margins) < 5 or not revenue:
            return None, ""
        # OI-010：营收本身强周期时，规模基准改用跨周期营收中位
        annual_rev = [float(r["TOTALOPERATEREVE"]) for r in annuals[:10]
                      if r.get("TOTALOPERATEREVE") is not None]
        scale_note = "当期 TTM 营收"
        if len(annual_rev) >= 6:
            downs = sum(1 for i in range(len(annual_rev) - 1) if annual_rev[i] < annual_rev[i + 1])
            down_ratio = downs / (len(annual_rev) - 1)
            rev_median = statistics.median(annual_rev)
            if down_ratio >= REVENUE_CYCLE_MIN_DOWN:
                revenue, scale_note = rev_median, f"跨周期营收中位（营收下降年占比 {down_ratio:.0%} ≥30%，判周期摆动）"
            elif down_ratio > REVENUE_GROWTH_MAX_DOWN:
                revenue = (revenue + rev_median) / 2
                scale_note = f"当期与跨周期营收中位取均值（下降年占比 {down_ratio:.0%}，判混合）"
            else:
                scale_note = f"当期 TTM 营收（营收下降年占比 {down_ratio:.0%} ≤20%，判结构性成长）"
        recent = statistics.median(margins[:5])
        window, label = margins[:10], "近 10 年"
        if len(margins) >= 10:
            prior = statistics.median(margins[5:10])
            if prior and abs(recent / prior - 1) > STRUCTURAL_BREAK_THRESHOLD:
                window, label = margins[:5], "近 5 年（结构断点检验命中）"
        # v1.41：中枢净利率改**加权口径**（用户指令）：0.5×TTM + 0.3×近3年中位 + 0.2×窗口中位。
        # 纯历史中位假设均值回归，而一致预期常与之相反——紫金矿业 22 家覆盖预期净利率
        # 17.7%→20.0%、神火股份 19 家预期 18.6%→19.1%，均为继续上行。加权让当期与近期
        # 得到应有权重，同时保留窗口中位作为长周期约束。
        ttm_margin = (profit_ttm / revenue_ttm * 100) if (profit_ttm and revenue_ttm and revenue_ttm > 0) else None
        window_median = statistics.median(window)
        margin = window_median
        weight_note = f"{label}净利率中位 {window_median:.2f}%"
        if ttm_margin is not None and ttm_margin > 0 and len(margins) >= 3:
            near3 = statistics.median(margins[:3])
            margin = 0.5 * ttm_margin + 0.3 * near3 + 0.2 * window_median
            weight_note = (f"加权净利率 {margin:.2f}%（0.5×TTM {ttm_margin:.2f}% + 0.3×近3年中位 "
                           f"{near3:.2f}% + 0.2×{label}中位 {window_median:.2f}%）")
            # 上限：不得超过一致预期隐含净利率——防止用当期高点外推超过分析师预期
            fwd, cnt, fy = consensus_median(evidence, 0)
            fwd_rev = None
            for row_ in ((evidence.get("profit_forecast") or {}).get("yctj_list") or []):
                if row_.get("YEAR") == fy and row_.get("TOTAL_OPERATE_INCOME"):
                    fwd_rev = float(row_["TOTAL_OPERATE_INCOME"])
            if fwd and fwd_rev and cnt >= 3:
                fwd_margin = fwd / fwd_rev * 100
                if margin > fwd_margin:
                    margin = fwd_margin
                    weight_note += f"；**上限收敛至 {fy}E 一致预期隐含净利率 {fwd_margin:.2f}%（{cnt} 家）**"
                else:
                    weight_note += f"；{fy}E 一致预期隐含 {fwd_margin:.2f}%（{cnt} 家）未构成上限"
        if margin <= 0:
            return None, ""
        return revenue * margin / 100, f"{scale_note} {revenue/1e8:.2f}亿 × {weight_note}"

    def cyclical_fallback(label: str) -> None:
        """F-2 / H-2：中枢归母 × 倍数 与 BVPS × 自身 PB 中位，取孰低（§6.5.5.1）。

        v1.42：中枢盈利**优先取一致预期**（前瞻），历史加权口径退为下位——财务数据滞后，
        而周期拐点先反映在研报里。安全阀是**修正方向**：一致预期在下调（>5%）时不采信
        前瞻锚，退回历史加权口径，因为研报对周期股有顺周期外推的通病（§6.3.5）。
        """
        nonlocal anchor, multiple, source, basis
        mid, mid_basis = mid_cycle_profit()
        fwd, fwd_count, fwd_year = best_consensus(evidence, (0, 1), min_coverage=3)
        direction, change, points = consensus_revision(evidence, 0)
        if fwd and fwd_count >= 3:
            if direction == "下调" and change is not None and change < -0.05:
                mid_basis += (f"；⚠一致预期**下调 {abs(change):.1%}**（{points} 份研报），"
                              f"按 §6.5.5.1 安全阀不采信前瞻锚，沿用历史加权口径")
            else:
                mid = fwd
                mid_basis = (f"{fwd_year}E 一致预期归母中位 {fwd/1e8:.2f}亿（{fwd_count} 家覆盖）"
                             f"——**前瞻锚优先于历史口径**（财务数据滞后、周期拐点先现于研报）；"
                             f"预期修正方向 **{direction}"
                             + (f" {change:+.1%}" if change is not None else "")
                             + f"**（{points} 份研报按发布日对半比较）")
        own_pe = band.get("pe_ttm_median")
        # 倍数取自身 5 年 PE 中位。锚为 T+1 一致预期时属前瞻 PE 口径（标准做法）；
        # 远期（T+2/T+3）锚才受 §6.5.2.1 同期约束禁用历史倍数，此处不适用。
        cycle_multiple = own_pe if own_pe and own_pe > 0 else terminal_pe
        if not (mid and cycle_multiple and shares):
            card["note"] = f"{label} 兜底不可算（年报期数不足或缺分层/股本）"
            return
        earnings_price = mid * cycle_multiple / 1e8 * low_coef / shares
        book_price = bvps * pb_median * low_coef if (bvps and pb_median) else None
        use_book = book_price is not None and book_price < earnings_price
        card["anchor_quality"] = "fallback"
        if use_book:
            anchor, multiple, source = bvps, pb_median, "own_history_median"
            card["anchor_scope"] = "per_share"
            card["anchor_metric"] = "bvps"
            basis = (f"{label} 兜底（取孰低→PB 口径）：每股净资产 {bvps:.2f} 元 × 自身 5 年 PB 中位 {pb_median}"
                     f"；对照口径 中枢归母 {mid/1e8:.2f}亿 × 自身 PE 中位 {cycle_multiple}（更高，未采用）")
        else:
            anchor, multiple, source = mid, cycle_multiple, ("own_history_median" if own_pe else "required_return")
            card["anchor_metric"] = "mid_cycle_profit"
            basis = (f"{label} 兜底（取孰低→中枢盈利口径）：中枢归母 = {mid_basis} = {mid/1e8:.2f}亿"
                     f"；× 自身 5 年 PE 中位 {cycle_multiple}（同期口径）"
                     + (f"；对照口径 BVPS×PB中位 更高，未采用" if book_price else ""))
        card["upgrade_path"] = ("资源储量与 NAV（储量报告/年报储量披露）" if label == "F-2"
                                else "中枢 EBITDA 与同业成熟期 EV/EBITDA")


    if tag_letter == "A":
        anchor = ttm(periods, "KCFJCXSYJLR")
        sr = shareholder_return(code)
        mv = manual_verdict(code)
        multiple, conv = deducted_pe_median(evidence, band.get("pe_ttm_median"))
        source = "own_history_median"
        if mv and mv.get("pe_median_usable") == "no":
            # 人工复核判定劣化确凿 → 历史 PE 中位锚在劣化前的盈利水平上，不可沿用。
            # 改以一致预期为锚（若覆盖足够），并标脆弱。
            fwd_a, cnt_a, fy_a = best_consensus(evidence, (0, 1), min_coverage=3)
            card["band_fragile"] = "true"
            if fwd_a:
                anchor = fwd_a
                card["anchor_metric"] = "forward_normalized_profit"
                card["manual_verdict"] = mv["verdict"]
                basis = (f"A-2 人工重估（{mv['verdict']}）：**历史 PE 中位不可沿用**——"
                         f"{mv['evidence'][:110]}。改以 {fy_a}E 一致预期归母 {fwd_a/1e8:.2f}亿"
                         f"（{cnt_a} 家）为锚 × 自身 5 年 PE 中位 {multiple}{conv}")
            else:
                card["manual_verdict"] = mv["verdict"] + "（一致预期覆盖不足，沿用 A-2 并标脆弱）"
        elif mv:
            card["manual_verdict"] = mv["verdict"]
            if mv.get("pe_median_usable") == "watch":
                card["band_fragile"] = "true"
        if not basis:
            basis = (f"A-2：扣非归母 TTM（四单季差分）{anchor/1e8:.2f}亿；"
                 f"5年 PE 中位 {band.get('pe_ttm_median')} → {multiple}{conv}"
                     f"（窗口 {band.get('window_start','')[:10]}~{band.get('window_end','')[:10]}，"
                     f"现分位 {band.get('pe_ttm_pct_rank')}%）") if anchor and multiple else ""
        # A-1（§6.5.3 双口径强制，v1.34 结 OI-008）：股东回报 Gordon 口径
        if sr and anchor and multiple and shares:
            roe_rows = [float(r["ROEJQ"]) for r in annuals[:3] if r.get("ROEJQ") is not None]
            # 分红为已披露年度口径，分母同口径（§6.5.2.2）
            profit = ttm(reported_only(periods), "PARENTNETPROFIT")
            payout = (sr["cash"] / profit) if (profit and profit > 0) else None
            growth_raw = (statistics.median(roe_rows) / 100 * (1 - min(payout, 1.0))
                          if (roe_rows and payout is not None) else PERPETUAL_G_CAP)
            growth = min(PERPETUAL_G_CAP, max(0.0, growth_raw))
            growth = min(growth, A1_REQUIRED_RETURN - GORDON_MIN_SPREAD)
            distributable = sr["cash"] + sr["cancel_rate"] * (quote.get("total_market_cap") or 0)
            # v1.41：改用两阶段 DCF——单阶段 Gordon 在 g 逼近 r 时发散，才需要 g≤2.5% 门槛；
            # 两阶段消除该约束，A-1 因此对**还在增长的公司**也可用（原门槛把它们全挡在外）。
            a1_fair = two_stage_dcf(distributable, min(growth_raw, 0.12),
                                    PERPETUAL_G_CAP, A1_REQUIRED_RETURN) / 1e8 / shares
            a1_lo_coef, a1_hi_coef = A2_COEFS.get(tier_key, (0.85, 1.05))
            a1_low, a1_high = a1_fair * a1_lo_coef, a1_fair * a1_hi_coef
            a2_mid = anchor / 1e8 * multiple * (low_coef + high_coef) / 2 / shares
            a1_mid = (a1_low + a1_high) / 2
            sustainable_g = (statistics.median(roe_rows) / 100 * (1 - min(payout, 1.0))
                             if (roe_rows and payout is not None) else None)
            # v1.41 实测否决「A-1 定带」：改用两阶段 DCF 并取消 g 门槛后，A-1 为 21 家定带，
            # 但结果不通过常识检验——贵州茅台得 868-1110 而现价 1205 判高估，其 PE 仅 18.2、
            # 股息率约 4%、内生增长 7%，预期回报明显高于 r=8.5%。**根因：A-1 的锚是「分配
            # 给股东的现金」，对高 ROE 留存型公司系统性低估**——茅台仅留存 12.5% 却以 32.5%
            # ROE 再投资，该部分价值需 FCFE/owner earnings 才能抓住，而本地无资本开支数据。
            # 故 A-1 **不定带，只作交叉校验**；其真正有用的输出是**现价反解的隐含折现率**，
            # 它可直接与机会成本比较，并按 §6.6 A 档标准读档（≥12% 低估 … <4% 高估）。
            a1_eligible = False
            cap_now = float(quote.get("total_market_cap") or 0)
            dcf_value = two_stage_dcf(distributable, min(growth_raw, 0.12), PERPETUAL_G_CAP, A1_REQUIRED_RETURN)
            implied_r = implied_discount_rate(cap_now, distributable, min(growth_raw, 0.12), PERPETUAL_G_CAP)
            if implied_r is not None:
                card["implied_return"] = f"{implied_r:.4f}"
                card["implied_return_tier"] = (
                    "低估" if implied_r >= 0.12 else "较低估" if implied_r >= 0.08 else
                    "中性" if implied_r >= 0.06 else "较高估" if implied_r >= 0.04 else "高估")
            dcf_note = (f"两阶段DCF（{DCF_STAGE1_YEARS}年 g1={min(growth_raw,0.12):.2%}→永续 {PERPETUAL_G_CAP:.1%}，"
                        f"r={A1_REQUIRED_RETURN:.1%}）每股 {dcf_value/1e8/shares:.4g}"
                        + (f"；**现价反解隐含折现率 r≈{implied_r:.1%} → 按 §6.6 A 档标准读作「"
                           f"{card['implied_return_tier']}」**（≥12%低估/8-12%较低估/6-8%中性/4-6%较高估/<4%高估）。"
                           f"注：A-1 锚为分配现金，对高 ROE 留存型公司偏低，故只作交叉校验不定带"
                           if implied_r else ""))
            gate = ("参与取孰低" if a1_eligible else
                    (f"分红率 {payout:.0%} <{A1_MIN_PAYOUT:.0%}，仅作对照" if (payout or 0) < A1_MIN_PAYOUT else
                     f"可持续内生增长 {sustainable_g:.1%} > 永续上限 {PERPETUAL_G_CAP:.1%}"
                     f"（单阶段 Gordon 会结构性低估），仅作对照"))
            card["band_sensitivity"] = (
                f"A-1 股东回报口径：{sr['year']} 年现金分红 {sr['cash']/1e8:.1f}亿 + 回购注销率 "
                f"{sr['cancel_rate']:.2%} = 可分配现金 {distributable/1e8:.1f}亿；g={growth:.2%}"
                f"（分红率 {payout:.0%}，{gate}）→ 带 {a1_low:.4g}~{a1_high:.4g}；A-2 带中值 {a2_mid:.4g}。"
                f"｜{dcf_note}")
            # v1.47：**背离只在两法都通过适用性门槛时才成立**。A-1 被 §6.5.3 的两条
            # 前置（分红率 ≥60%、可持续内生增长 ≤2.5%）挡在定带之外时，我们已经判定
            # 它的模型假设对这家公司不成立——一个**已被判定不适用**的方法给出不同的数，
            # 是预期之中的事，不含任何信息。v1.45 据此建的 `method_divergence` 卖出抑制
            # 因此建在一个空信号上：全池 23 个背离行**无一例外**都是 A-1 被门槛挡掉的，
            # 「两法失效方式不同」的说法在这 23 行上根本不适用（它们只有一法在用）。
            if a1_eligible and a2_mid and abs(a1_mid / a2_mid - 1) > A1_A2_DIVERGENCE:
                card["band_fragile"] = "true"
                # §6.5.3（v1.41 定，v1.45 落地为字段，结 OI-016）：两法背离 >25% 时
                # **不得据较低的那条发卖出提醒**——A-2 是相对法、有「看不见系统性错价」
                # 的构造性盲区，A-1 是绝对法、有参数敏感性，二者失效方式不同。取孰低对
                # 买入侧是保守的（正确），反过来当「贵」的证据不成立。同下限带与周期假设
                # 未决的处置。此前该规则只存在于本注释里：池物化不读 `band_fragile`，
                # 全池 22 个背离行中唯一落在 trim_alert 的美的集团照发减仓提醒。
                card["method_divergence"] = f"{abs(a1_mid / a2_mid - 1):.4f}"
                # v1.45 更名：`a1_mid` 是 **A-1 Gordon 带中值**，不是两阶段 DCF 每股值
                # （美的：Gordon 中值 102.7 vs 两阶段 DCF 108.1），旧标签把两个量混称。
                card["cycle_note"] = ((card.get("cycle_note") or "")
                    + f"⚑A-1/A-2 背离 {abs(a1_mid/a2_mid-1):.0%}"
                      f"（A-1 股东回报口径带中值 {a1_mid:.4g} vs A-2 相对法带中值 {a2_mid:.4g}）"
                      f"——按 §6.5.3 不得据较低的一条发卖出提醒。")
            # §6.5.3 取孰低——A-1 参与定带须**同时**满足两条：
            #   ① 分红率 ≥60%（现金分配是主要价值实现途径）
            #   ② **可持续内生增长 ≤ 永续上限**（ROE × 留存率 ≤ 2.5%）
            # 第②条是关键：单阶段 Gordon 只对「再投资增长已低于永续上限」的真稳态公司
            # 成立。对还能以高于永续增长率再投资的公司，把 g 截断到 2.5% 会结构性低估
            # ——贵州茅台 ROE 32.5%×留存 21% = 6.8%，截断后 A-1 给 1158-1479，
            # 而 A-2 为 1792-2290；国电南瑞同形态。这类公司需两阶段模型，本版不建，
            # A-1 只写入敏感度作对照。
            if a1_eligible and a1_high < anchor / 1e8 * multiple * high_coef / shares:
                # §6.5.2 A-1 是**形态2 收益率型**：带 = 锚 ÷ [rate_high, rate_low]，
                # 带系数不参与（恒为 1），倍数字段填 rate 区间。
                anchor = distributable
                multiple = round(1 / (A1_REQUIRED_RETURN - growth), 4)
                card["anchor_metric"] = "annual_distributable_cash"
                card["anchor_scope"] = "market_cap"
                low_coef, high_coef = a1_lo_coef, a1_hi_coef
                card["band_low_coef"], card["band_high_coef"] = low_coef, high_coef
                source = "required_return"
                basis = (f"A-1 两阶段DCF（与 A-2 取孰低，本行 A-1 更低）：可分配现金 {distributable/1e8:.1f}亿"
                         f"（{sr['year']} 现金分红 + 回购注销），{DCF_STAGE1_YEARS} 年 g1={min(growth_raw,0.12):.2%}"
                         f"→永续 {PERPETUAL_G_CAP:.1%}，r={A1_REQUIRED_RETURN:.1%} × 分层系数 [{low_coef}, {high_coef}]")
    elif tag_letter == "C":
        value, count, year = best_consensus(evidence, (0, 1), min_coverage=2)
        if value and count == 2:
            card["band_fragile"] = "true"
            card["anchor_quality"] = "fallback"
            card["upgrade_path"] = "研报覆盖补至 ≥3 家"
        if value:
            anchor = value
            # g 取覆盖达标的最长可算区间（优先三年，退而两年），按实际年数年化
            far_value, far_count, far_year = best_consensus(evidence, (2, 1))
            if far_value and far_year and far_year > year and anchor > 0:
                span = far_year - year
                cagr = (far_value / anchor) ** (1 / span) - 1
                multiple = round(cagr * 100, 2)
                source = "required_return"
                basis = (f"{year}E 归母中位数 {anchor/1e8:.2f}亿（{count} 家研报）；"
                         f"g = {year}E→{far_year}E 一致预期归母 CAGR {multiple}%"
                         f"（{span} 年，{far_count} 家覆盖；带系数即 PEG 1.0-1.5）")
        if not anchor or not multiple:
            # 覆盖 ≤1 家：改用自算口径——TTM 实际扣非归母 × 历史实现 3 年 CAGR（§6.5.5.1）
            profit_ttm = ttm(periods, "KCFJCXSYJLR")
            realized = [float(r["PARENTNETPROFIT"]) for r in annuals if r.get("PARENTNETPROFIT") is not None]
            if profit_ttm and profit_ttm > 0 and len(realized) >= 4 and realized[3] > 0:
                realized_cagr = (realized[0] / realized[3]) ** (1 / 3) - 1
                capped = max(0.0, min(realized_cagr, 0.30))
                anchor, multiple, source = profit_ttm, round(capped * 100, 2), "required_return"
                card["anchor_quality"] = "fallback"
                # 与 A-2 口径区分：同为 TTM 扣非归母，但倍数是自算增速、系数是 PEG 带
                card["anchor_metric"] = "realized_growth_profit"
                card["upgrade_path"] = "研报覆盖补至 ≥3 家 → 前瞻一致预期口径"
                basis = (f"C 兜底（覆盖 ≤1 家，改自算口径）：扣非归母 TTM {anchor/1e8:.2f}亿"
                         f"；g = 历史实现 3 年归母 CAGR {realized_cagr:.1%}（封顶 30% 后取 {capped:.1%}）"
                         f"；带系数即 PEG 1.0-1.5")
                if capped <= 0:
                    # 增长前提不成立 → 按 §6.5.0 重走判定顺序：净利率低于历史中枢=困境(E 口径)，
                    # 否则=无增长但盈利稳定(A-2 口径)。两者都不要求增长。
                    anchor = multiple = None
                    margins = [float(r["XSJLL"]) for r in annuals if r.get("XSJLL") is not None]
                    # 现净利率是跨字段相除，须同口径（§6.5.2.2）
                    margin_profit, revenue = ttm_same_vintage(periods, "KCFJCXSYJLR", "TOTALOPERATEREVE")
                    pe_med = band.get("pe_ttm_median")
                    current_margin = (margin_profit / revenue * 100) if (revenue and margin_profit) else None
                    mid_margin = statistics.median(margins) if margins else None
                    if mid_margin and current_margin is not None and pe_med and revenue:
                        if current_margin < mid_margin * 0.8:
                            anchor = revenue * mid_margin / 100
                            multiple, source = pe_med, "own_history_median"
                            card["anchor_quality"] = "fallback"
                            card["anchor_metric"] = "repaired_normalized_profit"
                            card["band_low_coef"], card["band_high_coef"] = (0.85, 1.00)
                            low_coef, high_coef = (0.85, 1.00)
                            card["upgrade_path"] = "增长证伪，按 §6.5.0 复核应否改判 E 落难白马"
                            basis = (f"C 增长前提不成立（历史实现 3 年 CAGR {realized_cagr:.1%} ≤0）→ 改按 E 修复口径："
                                     f"TTM 营收 {revenue/1e8:.2f}亿 × 历史中枢净利率 {mid_margin:.2f}%"
                                     f"（现净利率 {current_margin:.2f}%，处中枢 80% 以下=困境）"
                                     f"= {anchor/1e8:.2f}亿 × 自身 5 年 PE 中位 {pe_med}")
                        else:
                            anchor = profit_ttm
                            multiple, source = pe_med, "own_history_median"
                            card["anchor_quality"] = "fallback"
                            card["anchor_metric"] = "normalized_profit"
                            low_coef, high_coef = A2_COEFS.get(tier_key, (0.85, 1.05))
                            card["band_low_coef"], card["band_high_coef"] = low_coef, high_coef
                            card["upgrade_path"] = "增长证伪，按 §6.5.0 复核应否改判 A 现金流复利"
                            basis = (f"C 增长前提不成立（历史实现 3 年 CAGR {realized_cagr:.1%} ≤0）→ 改按 A-2 口径："
                                     f"扣非归母 TTM {profit_ttm/1e8:.2f}亿 × 自身 5 年 PE 中位 {pe_med}"
                                     f"（现净利率 {current_margin:.2f}% 未低于中枢 {mid_margin:.2f}% 的 80%，属无增长而非困境）")
                    else:
                        card["note"] = "C 增长前提不成立且净利率/PE 中位不可得"
            else:
                card["note"] = "C 兜底不可算（缺 TTM 扣非或年报期数 <4）"
    elif tag_letter == "D":
        # §6.5.2「未来 2-3 年正常化归母」：取覆盖达标的最远年份（第 3 年优先，退第 2 年）
        value, count, year = best_consensus(evidence, (2, 1), min_coverage=2)
        rate = terminal_rate
        if value and count == 2:
            card["band_fragile"] = "true"
            card["anchor_quality"] = "fallback"
            card["upgrade_path"] = "研报覆盖补至 ≥3 家"
        present, pv_note = forward_present_value(code, value or 0, year, AS_OF_YEAR, rate, terminal_pe)
        if value and present:
            years = max(1, (year or AS_OF_YEAR) - AS_OF_YEAR)
            anchor, source = value, "required_return"
            multiple = round(terminal_pe / (1 + rate) ** years, 4)   # 倍数含折现，保证可复算
            # v1.46（结 OI-017）：**这一支不再置 `band_is_floor`**。终值倍数是
            # `1/(r − TERMINAL_G)`，TERMINAL_G=3% 即已把窗口后的永续增长计入带内；
            # 它缺的只是「高于 3% 的超额增长」，而任何 DCF 都缺这个。把它当下限，
            # 等于对 65 家（全池 88 个下限带的 74%）永久免除提醒卖出。§6.5.5.1 第 3 条
            # 本来也只点名「D 的 **≤1 家覆盖**口径不含成长」，从未把 D primary 算进去
            # ——v1.32 的实现比它自己的规则宽。
            basis = (f"{year}E 正常化归母中位数 {anchor/1e8:.2f}亿（{count} 家覆盖）× {multiple} "
                     f"= 现值口径；{pv_note}。终值倍数 1/(r−{TERMINAL_G:.0%}) **已含永续增长**，"
                     f"缺的只是高于 {TERMINAL_G:.0%} 的超额增长（按 §6.5.6 成长期权补）")
        elif rate:
            # 覆盖 ≤1 家：base 带只按已兑现盈利建，成长部分走 §6.5.6 成长期权
            profit_ttm = ttm(periods, "KCFJCXSYJLR")
            if profit_ttm and profit_ttm > 0:
                anchor, multiple, source = profit_ttm, terminal_pe, "required_return"
                card["anchor_quality"] = "fallback"
                card["anchor_metric"] = "normalized_profit"
                card["band_is_floor"] = "true"   # D ≤1 家覆盖：成长不计入 base 带
                card["upgrade_path"] = "研报覆盖补至 ≥3 家 → 2-3 年正常化归母口径；成长部分按 §6.5.6 成长期权补入"
                basis = (f"D 兜底（覆盖 ≤1 家，base 带只按已兑现盈利）：扣非归母 TTM {profit_ttm/1e8:.2f}亿"
                         f" × 终值 PE {terminal_pe}x——**成长不计入 base 带**，为下限；"
                         f"完整价值须经 §6.5.6 成长期权或补齐覆盖后上修")
            else:
                card["note"] = "D 兜底不可算（TTM 扣非归母 ≤0）"
        else:
            card["note"] = f"D 类终值倍数需 L1/L2/L3 分层，实得 '{quality_tier}'"
    elif tag_letter == "E":
        rows = annual_rows(periods)
        margins = [float(r["XSJLL"]) for r in rows if r.get("XSJLL") is not None]
        revenue = ttm(periods, "TOTALOPERATEREVE")
        if margins and revenue:
            normal_margin = statistics.median(margins)
            anchor = revenue * normal_margin / 100
            multiple = band.get("pe_ttm_median")
            source = "own_history_median"
            basis = (f"修复后归母 = TTM 营收 {revenue/1e8:.2f}亿 × 历史中枢净利率 {normal_margin:.2f}%"
                     f"（{len(margins)} 个年报期中位）= {anchor/1e8:.2f}亿；PE 取 5 年中位 {multiple}")
    elif tag_letter == "H":
        cyclical_fallback("H-2")
    elif tag_letter == "F":
        cyclical_fallback("F-2")
    elif tag_letter in ("K",):
        sr = shareholder_return(code)
        if sr and shares and sr["cash"] > 0:
            # K primary（v1.34 恢复）：Gordon DPS/(r−g)
            dps = sr["cash"] / 1e8 / shares
            # 分红为已披露年度口径，分母同口径（§6.5.2.2）
            profit = ttm(reported_only(periods), "PARENTNETPROFIT")
            payout = (sr["cash"] / profit) if (profit and profit > 0) else 1.0
            roe_rows = [float(r["ROEJQ"]) for r in annuals[:3] if r.get("ROEJQ") is not None]
            growth = min(PERPETUAL_G_CAP, max(0.0, (statistics.median(roe_rows) / 100 * (1 - min(payout, 1.0)))
                                              if roe_rows else 0.0))
            # g 逼近或超过 r 时 Gordon 发散（判例：长江电力 g=3.5% ≥ r_low=3.0% 得出负带）
            growth = min(growth, K_REQUIRED_RETURN - GORDON_MIN_SPREAD)
            k_lo, k_hi = A2_COEFS.get(tier_key, (0.85, 1.05))
            anchor, multiple, source = dps, round(1 / (K_REQUIRED_RETURN - growth), 4), "gordon"
            card["anchor_metric"] = "dps"
            card["anchor_scope"] = "per_share"
            card["band_low_coef"], card["band_high_coef"] = k_lo, k_hi
            low_coef, high_coef = k_lo, k_hi
            card["anchor_quality"] = "primary"
            card["upgrade_path"] = ""
            low = dps * multiple * k_lo
            high = dps * multiple * k_hi
            # K primary 本身就是股东回报口径，不再叠加通用校验二（同一信息用两次）
            card["fair_price_low"], card["fair_price_high"] = f"{low:.4g}", f"{high:.4g}"
            card["band_sensitivity"] = (f"Gordon：DPS {dps:.3f} 元（{sr['year']} 现金分红 {sr['cash']/1e8:.1f}亿"
                                        f"÷ {shares:.2f}亿股）÷ (r {K_REQUIRED_RETURN:.1%} − g {growth:.2%})"
                                        f" × 分层系数 [{k_lo}, {k_hi}]（分红率 {payout:.0%}）")
            # 与 K-2（PE 中枢回归）取孰低——r∈[3.0%,4.5%] 是按受监管长久期资产校准的，
            # 套到非监管的稳态消费公司过于宽松；取孰低让口径自己纠偏（同 A/J/F-2 的处理）。
            k2_profit = ttm(periods, "KCFJCXSYJLR")
            k2_pe, k2_conv = deducted_pe_median(evidence, band.get("pe_ttm_median"))
            k2_lo, k2_hi = A2_COEFS.get(tier_key, (0.85, 1.05))
            k2_high = (k2_profit / 1e8 * k2_pe * k2_hi / shares) if (k2_profit and k2_pe) else None
            if k2_high and k2_high < high:
                anchor, multiple, source = k2_profit, k2_pe, "own_history_median"
                card["anchor_metric"] = "normalized_profit"
                card["anchor_scope"] = "market_cap"
                card["band_low_coef"], card["band_high_coef"] = k2_lo, k2_hi
                card["anchor_quality"] = "fallback"
                card["upgrade_path"] = "—（Gordon 已可算，本行按取孰低采用 K-2）"
                low_coef, high_coef = k2_lo, k2_hi
                card["fair_price_low"] = card["fair_price_high"] = ""
                card["band_sensitivity"] = (
                    f"K primary Gordon 带 {low:.4g}~{high:.4g}（DPS {dps:.3f}，r {K_REQUIRED_RETURN:.1%}，"
                    f"g={growth:.2%}）**高于 K-2，未采用**；"
                    f"K-2：扣非归母 TTM {k2_profit/1e8:.2f}亿 × PE 中位 {k2_pe}{k2_conv}")
                basis = card["band_sensitivity"]
                k2_div = abs((low + high) / 2 / ((k2_profit / 1e8 * k2_pe * (k2_lo + k2_hi) / 2 / shares)) - 1)
                if k2_div > A1_A2_DIVERGENCE:
                    card["band_fragile"] = "true"
                    # 同 A-1/A-2：K primary Gordon 与 K-2 相对法失效方式不同，取孰低
                    # 只对买入侧保守，不构成「贵」的证据（§6.5.3，结 OI-016）
                    card["method_divergence"] = f"{k2_div:.4f}"
                    card["cycle_note"] = ((card.get("cycle_note") or "")
                        + f"⚑K/K-2 背离 {k2_div:.0%}——按 §6.5.3 不得据较低的一条发卖出提醒。")
            else:
                card["anchor_value"] = f"{dps:.4f}"
                card["multiple_or_rate"] = multiple
                card["multiple_source"] = "gordon"
                card["anchor_basis"] = card["band_sensitivity"]
                return card
        # K-2 兜底：稳态公司的 PE 中枢回归（同 A-2）
        anchor = ttm(periods, "KCFJCXSYJLR")
        multiple = band.get("pe_ttm_median")
        source = "own_history_median"
        card["anchor_quality"] = "fallback"
        card["anchor_metric"] = "normalized_profit"
        multiple, conv = deducted_pe_median(evidence, multiple)
        low_coef, high_coef = A2_COEFS.get(tier_key, (0.85, 1.05))
        card["band_low_coef"], card["band_high_coef"] = low_coef, high_coef
        card["upgrade_path"] = "可持续分红率（分红预案/章程承诺/近三年实际）→ Gordon DPS/(r−g)"
        basis = (f"K-2 兜底：扣非归母 TTM {anchor/1e8:.2f}亿 × 自身 5 年 PE 中位 {multiple}{conv}"
                 f"（稳态公司的 PE 中枢回归；primary 的 DDM 待补分红率）") if anchor and multiple else ""
    elif tag_letter == "N":
        revenue = ttm(periods, "TOTALOPERATEREVE")
        margins = [float(r["XSJLL"]) for r in annuals if r.get("XSJLL") is not None]
        if revenue and margins and terminal_pe:
            peak = max(margins)
            normalized = peak * 0.85
            anchor = revenue * normalized / 100
            multiple, source = terminal_pe, "required_return"
            card["anchor_quality"] = "fallback"
            card["band_is_floor"] = "true"   # EPV 按定义剥离增长，为下限
            card["upgrade_path"] = "同业成熟期归一化经营利润率、合同负债占比"
            basis = (f"N-2 兜底 EPV：TTM 营收 {revenue/1e8:.2f}亿 × 归一化净利率 {normalized:.2f}%"
                     f"（自身历史峰值 {peak:.2f}% × 85%，§6.5.4 授权）= {anchor/1e8:.2f}亿"
                     f"；× 终值 PE {terminal_pe}x")
        else:
            card["note"] = "N-2 兜底不可算（缺营收/净利率历史或分层）"
    elif tag_letter in ("M", "P"):
        value, count, year = best_consensus(evidence, (0, 1), min_coverage=2)
        present, pv_note = forward_present_value(code, value or 0, year, AS_OF_YEAR, terminal_rate, terminal_pe)
        if value and present:
            years = max(1, (year or AS_OF_YEAR) - AS_OF_YEAR)
            anchor, source = value, "required_return"
            multiple = round(terminal_pe / (1 + terminal_rate) ** years, 4)
            card["anchor_quality"] = "fallback"
            card["anchor_metric"] = "forward_normalized_profit"
            card["band_is_floor"] = "true"   # M-2/P-2 明确不含管线/订单价值
            label = "管线价值" if tag_letter == "M" else "在手订单溢价"
            card["upgrade_path"] = ("管线阶段、适应症空间、BD 条款 → SOTP + rNPV" if tag_letter == "M"
                                    else "在手订单额与交付排期 → backlog 年化归母")
            basis = (f"{tag_letter}-2 下限带：{year}E 归母中位数 {anchor/1e8:.2f}亿（{count} 家覆盖）"
                     f"× {multiple}（现值口径；{pv_note}）——**{label}记 0**，为不含未兑现价值的下限；"
                     f"完整价值须经 §6.5.6 成长期权或补齐外部取证后上修")
        else:
            card["note"] = f"{tag_letter}-2 下限带不可算（研报覆盖 <2 家或缺分层）"
    elif tag_letter == "J":
        stats = (evidence.get("profit_forecast") or {}).get("yctj_list") or []
        forecast = [r for r in stats if r.get("YEAR_MARK") == "E" and r.get("BVPS") and r.get("ROE")]
        if forecast:
            row = forecast[0]
            bvps, roe = float(row["BVPS"]), float(row["ROE"]) / 100
            g = min(MAX_G, roe)          # 分红率未知时取上限；有分红率须改用 ROE×(1−分红率)
            implied_pb = (roe - g) / (COE_BANK - g)
            pb_median = band.get("pb_median")
            chosen, source = (implied_pb, "implied_pb")
            if pb_median and pb_median < implied_pb:
                chosen, source = (pb_median, "own_history_median")
            anchor, multiple = bvps, chosen
            card["anchor_scope"] = "per_share"
            deviation = abs(implied_pb / pb_median - 1) if pb_median else 0
            if deviation > 0.30:
                card["band_fragile"] = "true"
            implied_coe = (roe - g) / band["current_pb"] + g if band.get("current_pb") else None
            basis = (f"{row['YEAR']}E BVPS {bvps:.2f} 元（{row.get('BVPS_COUNT')} 家）；"
                     f"J-1 隐含 PB {implied_pb:.3f}（ROE {roe:.2%}，g {g:.2%}，COE {COE_BANK:.2%}）vs "
                     f"J-2 自身 5 年 PB 中位 {pb_median} → **取孰低 {chosen:.3f}**；"
                     + (f"反解当前隐含 COE {implied_coe:.2%}（现 PB {band['current_pb']:.3f}）"
                        if implied_coe else ""))

    if not (anchor and multiple) and bvps and pb_median:
        # §6.5.5.1 最终兜底：净资产口径。PE 系口径全部失效（亏损、上市不足 4 年、
        # 增速不可算）时，账面价值仍是可计量的锚；周期与亏损公司的标准做法。
        anchor, multiple, source = bvps, pb_median, "own_history_median"
        card["anchor_scope"] = "per_share"
        card["anchor_metric"] = "bvps"
        low_coef, high_coef = (0.85, 1.00)
        card["band_low_coef"], card["band_high_coef"] = low_coef, high_coef
        card["anchor_quality"] = "fallback"
        card["upgrade_path"] = card["upgrade_path"] or "盈利转正或研报覆盖补齐后改用盈利口径"
        basis = (f"最终兜底（净资产口径）：每股净资产 {bvps:.2f} 元 × 自身 5 年 PB 中位 {pb_median}"
                 f"——盈利口径失效（{card.get('note') or '亏损/历史不足/增速不可算'}），"
                 f"账面价值为唯一可计量锚；须按 §6.5.3 通用校验一核对清算价值地板")
        card["note"] = ""


    mv_any = manual_verdict(code)
    if mv_any and not card.get("manual_verdict"):
        card["manual_verdict"] = mv_any["verdict"]
        if mv_any.get("pe_median_usable") in ("no", "watch"):
            card["band_fragile"] = "true"

    if anchor and multiple:
        card["anchor_value"] = f"{anchor/1e8:.4f}" if card["anchor_scope"] != "per_share" else f"{anchor:.4f}"
        card["anchor_scope"] = card["anchor_scope"] or "market_cap"
        card["anchor_basis"] = basis
        card["multiple_or_rate"] = f"{multiple}"
        card["multiple_source"] = source
        divisor = shares if card["anchor_scope"] == "market_cap" else 1.0
        if divisor:
            value = float(card["anchor_value"]) * float(multiple)
            low, high = value * low_coef / divisor, value * high_coef / divisor
            sens_low = value * 0.85 * low_coef / divisor
            sens_high = value * 1.15 * high_coef / divisor
            _, _, sr_note = shareholder_return_check(low, high)
            # v1.40：倍数取自身历史中位时，若现 PE 处 5 年极端分位，说明**倍数锚在另一个
            # 估值制度里**——中位数会把旧制度锁进结论。全池实测 81 家用相对法，其中 39 家
            # （48%）处极端分位。只标记不改带：分位本身是市场意见，不能反过来当成事实。
            pct_rank = band.get("pe_ttm_pct_rank")
            if (card["multiple_source"] == "own_history_median" and pct_rank is not None
                    and (pct_rank <= DCF_PERCENTILE_EXTREME[0] or pct_rank >= DCF_PERCENTILE_EXTREME[1])):
                side = "低位" if pct_rank <= DCF_PERCENTILE_EXTREME[0] else "高位"
                trend, detail = business_trend_test(evidence)
                if side == "低位":
                    verdict = ("**历史 PE 趋势可参考**（低估值无基本面劣化支撑，属情绪）"
                               if trend != "劣化" else "**历史中位不可信**——存在劣化，低估值反映真实恶化，须人工重估")
                else:
                    verdict = ("**历史 PE 趋势可参考**（高估值无基本面优化支撑，不可持续）"
                               if trend != "优化" else "**历史中位可能偏低**——存在优化，重估或为结构性，须人工重估")
                card["multiple_regime_flag"] = f"现PE处5年{pct_rank:.1f}%分位（{side}极端）｜业务趋势：{trend}（{detail}）｜{verdict}"
                if (side == "低位" and trend == "劣化") or (side == "高位" and trend == "优化"):
                    card["band_fragile"] = "true"
            # §6.5.4 运行率校验 + 情景带（v1.36）：把「这是周期顶还是新平台」的假设显式化。
            # 基准用 **TTM**（四个单季之和）而非单季×4——单季年化对季节性生意必然误报
            # （白酒一季度为旺季，山西汾酒/洋河/伊利首轮均被误标）。TTM 天然抵消季节性。
            run_rate = ttm(periods, "PARENTNETPROFIT")
            quarter_rate, run_date = latest_quarter_annualized(periods)
            anchor_abs = float(card["anchor_value"]) * (1e8 if card["anchor_scope"] == "market_cap" else 1)
            if (run_rate and run_rate > 0 and card["anchor_scope"] == "market_cap"
                    and anchor_abs < run_rate * RUN_RATE_FLOOR):
                ratio = anchor_abs / run_rate
                # 情景用 max(TTM, 最近季年化)——季度加速时 TTM 本身也滞后（美光判例）
                basis_rate = max(run_rate, quarter_rate or 0)
                scen_low = basis_rate / 1e8 * float(multiple) * low_coef / divisor
                scen_high = basis_rate / 1e8 * float(multiple) * high_coef / divisor
                card["cycle_assumption"] = "mean_reversion_assumed"
                card["scenario_band_low"], card["scenario_band_high"] = f"{scen_low:.4g}", f"{scen_high:.4g}"
                card["band_fragile"] = "true"
                # OI-011：反解市场隐含的超额利润年数 + 输出年数阶梯
                cap_now = float(quote.get("total_market_cap") or 0)
                t_rate = terminal_rate or 0.10
                # 阶梯必须与带用**同一个倍数**，否则 N=0 不还原本行的带、两者不可比。
                # 首版阶梯用终值 PE 而带用自身 PE 中位，神火股份 N=0 得 28.81 而带顶仅 20.99。
                t_pe = float(multiple) * (low_coef + high_coef) / 2
                # 超额用 TTM（稳定）而非 max(TTM, 单季年化)——单季年化用于情景带、不用于反解
                implied = implied_excess_years(cap_now, run_rate, anchor_abs, t_rate, t_pe) if cap_now else None
                ladder = "；".join(
                    f"N={n}年→{excess_profit_value(run_rate, anchor_abs, n, t_rate, t_pe)/1e8/shares:.4g}"
                    for n in EXCESS_YEARS_LADDER) if shares else ""
                excess_now = run_rate - anchor_abs
                if implied is not None:
                    card["implied_excess_years"] = f"{implied}"
                elif cap_now and excess_now > 0:
                    card["implied_excess_years"] = ">20"
                    card["cycle_gap_kind"] = "中枢水平分歧"
                else:
                    card["cycle_gap_kind"] = "运行率未超中枢"
                card["excess_years_ladder"] = ladder
                card["cycle_note"] = (
                    (f"市场隐含超额利润年数 **N≈{implied} 年**（现价反解）；每股价值阶梯：{ladder}。"
                     f"N 能否成立取决于扩产周期、技术门槛与新进入者产能规划——**可查证的事实**，"
                     f"不是估值参数。 ‖ " if implied is not None else
                     (f"⚑ 即使超额利润持续 20 年也接不上现价（阶梯：{ladder}）——**分歧不在持续年数，"
                      f"在中枢水平本身**：市场认为的正常盈利能力显著高于历史 10 年可支持的水平。"
                      f"应先复核中枢口径（营收基准、净利率窗口）而非讨论周期长度。 ‖ "
                      if card.get("cycle_gap_kind") == "中枢水平分歧" else ""))
                    + f"⚠周期假设显式化：锚 {anchor_abs/1e8:.1f}亿 仅为 TTM 归母 {run_rate/1e8:.1f}亿 的 "
                    f"{ratio:.2f} 倍（最近季年化 {(quarter_rate or 0)/1e8:.1f}亿，{run_date}）"
                    f"——本带**假设均值回归**。"
                    f"若为结构性变化（供给纪律、格局重构、需求台阶），运行率延续情景的带为 "
                    f"{scen_low:.4g}~{scen_high:.4g}，与本带相差 {scen_high / high:.1f} 倍。"
                    f"二者取舍是**供给侧判断**（在建产能、资本开支纪律、格局集中度），非财务数据可定；"
                    f"取得该证据前本行不触发 §14 提醒卖出（OI-011）。")
            card["fair_price_low"], card["fair_price_high"] = f"{low:.4g}", f"{high:.4g}"
            # §6.5.4 运行率不变量（v1.52，OI-018）：对每条带生效，与 anchor_scope 无关
            _ae = anchor_abs / 1e8 if card["anchor_scope"] == "market_cap" else None
            card["runrate_check"], _rrn = runrate_invariant(evidence, AS_OF_DATE, _ae)
            # §6.5.2.2：锚若用到已结束报告期的预告/快报，必须一眼可见——这是 OI-015
            # 的核心，锚的口径新旧决定了「贵」这个结论成不成立。
            anchor_field = ("KCFJCXSYJLR" if "扣非" in (basis or "") else "PARENTNETPROFIT")
            fc_note = forecast_note(periods, anchor_field) or forecast_note(periods, "TOTALOPERATEREVE")
            if fc_note:
                card["anchor_vintage"] = f"含已结束期预告/快报{fc_note}"
            extra = card.get("band_sensitivity") or ""
            card["band_sensitivity"] = (f"锚±15% → 带 {sens_low:.4g}~{sens_high:.4g}"
                                        f"（基准 {low:.4g}~{high:.4g}）；"
                                        + share_count_check(evidence, shares)
                                        + (f"｜{extra}" if extra else "")
                                        + (f"｜{sr_note}" if sr_note else "")
                                        + (f"｜{card.get('cycle_note') or ''}" if card.get("cycle_note") else "")
                                        + (f"｜⚑倍数制度提示：{card['multiple_regime_flag']}——"
                                           f"历史中位可能锚在另一个估值制度上" if card.get("multiple_regime_flag") else ""))
    elif not card["note"] and not card["needs_external"]:
        card["note"] = "锚定量或倍数取数失败，须人工补"

    return card


def main() -> int:
    parser = argparse.ArgumentParser(description="按 §6.5.2.1 口径计算建带卡草稿")
    parser.add_argument("--tags", type=Path, required=True, help="CSV: security_code,strategy_tag_letter")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()

    global AS_OF_DATE
    AS_OF_DATE = args.as_of          # §6.5.2.2：只有 REPORT_DATE ≤ as_of 的预告/快报才合成

    with args.tags.open(encoding="utf-8-sig") as handle:
        tags = list(csv.DictReader(handle))

    cards = [
        build_card(
            row["security_code"].zfill(6),
            row.get("security_name", ""),
            row["strategy_tag_letter"].strip().upper(),
            row.get("quality_tier", ""),
        )
        for row in tags
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(cards[0].keys()))
        writer.writeheader()
        writer.writerows(cards)

    computed = sum(1 for c in cards if c["fair_price_low"])
    external = sum(1 for c in cards if c["needs_external"])
    failed = sum(1 for c in cards if c["note"] and not c["needs_external"])
    print(f"建带卡草稿 {args.as_of}：{len(cards)} 家")
    print(f"  带已算出           {computed}")
    print(f"  待外部取证         {external}")
    print(f"  取数失败/须人工补  {failed}")
    # §15.2 第 3 条强制自检（v1.58）：**凡新增数据源或新增列，跑完必须核对非空行数**。
    # 四次静默失效的共同签名都是「某列/某源整体为空而无人察觉」——apply 只写非空值、
    # `band_derivation` 被硬写、`runrate_check` 没进 CARD_FIELDS、北交所后缀查不到财务。
    # 全空列几乎一定是接线错误而不是业务事实，故一律高声报出。
    total = len(cards)
    generic = [c for c in cards if c.get("band_derivation") != "dossier"]
    # 只由通用路径产出的列，分母用通用行而非全池——否则逐票档案位移会把正常列报成「全空」，
    # 告警一旦常态化就会被忽略，等于自检失效。
    GENERIC_ONLY = {"band_is_floor", "cycle_assumption", "scenario_band_low", "scenario_band_high",
                    "cycle_note", "implied_excess_years", "excess_years_ladder", "cycle_gap_kind",
                    "method_divergence", "multiple_regime_flag", "implied_return", "implied_return_tier",
                    "manual_verdict", "band_fragile", "upgrade_path", "anchor_vintage"}
    OPTIONAL = {"note", "needs_external", "runrate_override_reason"}
    alarms = []
    for k in cards[0]:
        if k in OPTIONAL:
            continue
        pop = generic if k in GENERIC_ONLY else cards
        if not pop:
            continue
        n = sum(1 for c in pop if str(c.get(k, "")).strip())
        if n == 0:
            alarms.append(f"{k}（0/{len(pop)}）")
    # 全空 ≠ 坏。真正的告警是「**本该命中却没写**」：用同一轮已算出的 `runrate_check`
    # 做一致性断言——通用 market_cap 行里凡 below_runrate 的，必须同时置 cycle_assumption。
    should = [c for c in generic
              if c.get("anchor_scope") == "market_cap" and c.get("runrate_check") == "below_runrate"]
    missing = [c for c in should if not str(c.get("cycle_assumption", "")).strip()]
    print(f"  列覆盖自检        全池 {total} 行、通用路径 {len(generic)} 行；全空列 {len(alarms)}")
    if missing:
        print(f"    ❌**一致性断言失败**：{len(missing)} 行 runrate_check=below_runrate 却未置 cycle_assumption —— "
              + "、".join(f"{c['security_code']}{c.get('security_name','')}" for c in missing[:10]))
    if alarms:
        print(f"    ⓘ全空列（§15.2 第 3 条须逐列确认是否有行本该命中；本轮 below_runrate 命中 {len(should)} 行）："
              + "、".join(alarms))
    # 数据源自检：财务期数为 0 的行——北交所判例正是全体为 0 而无提示
    noperiod = [c for c in cards if c.get("runrate_check") == "na_no_ttm"]
    if noperiod:
        print(f"    ⚠无 TTM 归母（财务期数缺失或为负）{len(noperiod)} 行："
              + "、".join(f"{c['security_code']}{c.get('security_name','')}" for c in noperiod[:12])
              + ("…" if len(noperiod) > 12 else ""))
    vintage = sum(1 for c in cards if c.get("anchor_vintage"))
    print(f"  锚含预告/快报      {vintage}（§6.5.2.2）")
    # §6.5.6 落地校验（v1.46，结 OI-017）：真·下限带（按定义完全不含成长/管线/订单）
    # 必须有成长期权，否则它的完整价值永远缺一块。此前 §6.5.6 成文而**全池执行 0 次**，
    # 且没有任何环节报告过这件事——「成文即视为落地」正是 OI-002 与 OI-017 同型的病根。
    # 故此处强制计数并打印：缺口可以存在，但不许再无声无息。
    floors = [c for c in cards if str(c.get("band_is_floor", "")).lower() == "true"]
    missing = [c for c in floors if not (c.get("growth_option_value") or "").strip()]
    print(f"  真·下限带          {len(floors)}；其中缺 §6.5.6 成长期权 {len(missing)}")
    if missing:
        print(f"    ⚠ 缺口清单（须由 §7 复核逐票补证据等级/实现概率/里程碑）："
              + "、".join(f"{c['security_code']}{c.get('security_name','')}" for c in missing[:30])
              + ("…" if len(missing) > 30 else ""))
    print(f"  输出：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
