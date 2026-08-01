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

# §6.5.3 A-1 / K primary / 通用校验二（v1.34，结 OI-008）
# v1.35（结 OI-009）：单点要求回报 + 固定带系数，带宽交回带系数控制。
# 原「rate 区间 [8%−g, 6%−g]」使带宽恒为 2.0 倍，档位分辨力退化。
A1_REQUIRED_RETURN = 0.070           # A-1 要求回报 = 10Y 国债 1.8% + 成熟股权风险溢价 5.2%
K_REQUIRED_RETURN = 0.065            # K   要求回报 = 10Y 国债 1.8% + 受监管长久期资产溢价 4.7%
# 永续增长上限：高分红成熟公司按定义把大部分利润分掉，留存不足以支撑更高的永续增长。
# 2.5% 对应「长期通胀 + 极低实际增长」，即公司长期存在但不再扩张，低于 §6.5.4 的通用
# 3.5% 上限。**它不是收益率目标**——Gordon 的 g 是终局增长假设，取高会让分母塌陷。
PERPETUAL_G_CAP = 0.025
A1_A2_DIVERGENCE = 0.25              # 双口径中值偏离 >25% 置 band_fragile（§6.5.3）
A1_MIN_PAYOUT = 0.60                 # A-1 参与定带的分红率门槛（辅条件）
GORDON_MIN_SPREAD = 0.015            # Gordon 分母下限：g 必须 ≤ r − 1.5pp，否则模型发散
DIVIDENDS_PATH = ROOT / "data/interim/a_share_dividends.csv"

# §6.5.4 运行率硬校验（v1.36，OI-001 的原始第 5 条，此前只写在文档、引擎实现 0 次）
RUN_RATE_FLOOR = 0.85            # 锚 < TTM 归母 × 0.85 即触发周期假设标记
# §6.5.4 超额利润持续年数（v1.38，结 OI-011）：把「周期顶 vs 结构性变化」的二选一，
# 换成一个连续量——超额利润还能持续几年。用户原述：「高利润持续的时间可能会比较长，
# 但也肯定不是无限期，取决于技术门槛以及新玩家是否大幅扩产」。
# 价值 = Σ(t=1..N) 运行率利润/(1+r)^t + 中枢利润 × 终值PE /(1+r)^N
EXCESS_YEARS_LADDER = (0, 2, 4, 6)      # 敏感度阶梯


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
    """年报行，按报告期倒序。"""
    return [p for p in periods if p.get("REPORT_TYPE") == "年报"]


def ttm(periods: list[dict], field: str) -> float | None:
    """§6.5.2.1 取数陷阱一：finance_periods 是累计口径，须差分成单季再求 TTM。

    单季 = 本期累计 − 同年上期累计（一季报本身即单季）。TTM = 最近四个单季之和。
    """
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
    return None


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
    revenue = ttm(evidence.get("finance_periods") or [], "TOTALOPERATEREVE")
    # §6.5.2.1 取数陷阱三：JYXJLYYSR 是**小数比率**（0.3644 = 36.44%），
    # 与同记录内的 XSJLL/ROEJQ（百分数）单位不同，不得再除以 100。
    ratios = [float(r["JYXJLYYSR"]) for r in rows if r.get("JYXJLYYSR") is not None]
    profit_ttm = ttm(evidence.get("finance_periods") or [], "PARENTNETPROFIT")
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


def build_card(code: str, name: str, tag_letter: str, quality_tier: str) -> dict:
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
        "cycle_assumption": "",
        "scenario_band_low": "",
        "scenario_band_high": "",
        "cycle_note": "",
        "implied_excess_years": "",
        "excess_years_ladder": "",
        "cycle_gap_kind": "",
        "band_sensitivity": "",
        "band_fragile": "false",
        "fair_price_low": "",
        "fair_price_high": "",
        "needs_external": "",
        "note": "",
    }
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

    periods = evidence.get("finance_periods") or []
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
        profit = ttm(periods, "PARENTNETPROFIT")
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
        revenue = ttm(periods, "TOTALOPERATEREVE")
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
        margin = statistics.median(window)
        if margin <= 0:
            return None, ""
        return revenue * margin / 100, (
            f"{scale_note} {revenue/1e8:.2f}亿 × {label}净利率中位 {margin:.2f}%")

    def cyclical_fallback(label: str) -> None:
        """F-2 / H-2：中枢归母 × 终值 PE 与 BVPS × 自身 PB 中位，取孰低（§6.5.5.1）。"""
        nonlocal anchor, multiple, source, basis
        mid, mid_basis = mid_cycle_profit()
        own_pe = band.get("pe_ttm_median")
        # 锚是「当期规模下的正常化盈利」→ 倍数取同期口径（自身 5 年 PE 中位），
        # 不用终值公式（那是给远期利润锚配的，§6.5.2.1 锚与倍数同期约束）。
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
        multiple, conv = deducted_pe_median(evidence, band.get("pe_ttm_median"))
        source = "own_history_median"
        basis = (f"A-2：扣非归母 TTM（四单季差分）{anchor/1e8:.2f}亿；"
                 f"5年 PE 中位 {band.get('pe_ttm_median')} → {multiple}{conv}"
                 f"（窗口 {band.get('window_start','')[:10]}~{band.get('window_end','')[:10]}，"
                 f"现分位 {band.get('pe_ttm_pct_rank')}%）") if anchor and multiple else ""
        # A-1（§6.5.3 双口径强制，v1.34 结 OI-008）：股东回报 Gordon 口径
        if sr and anchor and multiple and shares:
            roe_rows = [float(r["ROEJQ"]) for r in annuals[:3] if r.get("ROEJQ") is not None]
            profit = ttm(periods, "PARENTNETPROFIT")
            payout = (sr["cash"] / profit) if (profit and profit > 0) else None
            growth = PERPETUAL_G_CAP
            if roe_rows and payout is not None:
                growth = min(PERPETUAL_G_CAP, max(0.0, statistics.median(roe_rows) / 100 * (1 - min(payout, 1.0))))
            growth = min(growth, A1_REQUIRED_RETURN - GORDON_MIN_SPREAD)
            distributable = sr["cash"] + sr["cancel_rate"] * (quote.get("total_market_cap") or 0)
            a1_fair = distributable / (A1_REQUIRED_RETURN - growth) / 1e8 / shares
            a1_lo_coef, a1_hi_coef = A2_COEFS.get(tier_key, (0.85, 1.05))
            a1_low, a1_high = a1_fair * a1_lo_coef, a1_fair * a1_hi_coef
            a2_mid = anchor / 1e8 * multiple * (low_coef + high_coef) / 2 / shares
            a1_mid = (a1_low + a1_high) / 2
            sustainable_g = (statistics.median(roe_rows) / 100 * (1 - min(payout, 1.0))
                             if (roe_rows and payout is not None) else None)
            a1_eligible = ((payout or 0) >= A1_MIN_PAYOUT
                           and sustainable_g is not None and sustainable_g <= PERPETUAL_G_CAP)
            gate = ("参与取孰低" if a1_eligible else
                    (f"分红率 {payout:.0%} <{A1_MIN_PAYOUT:.0%}，仅作对照" if (payout or 0) < A1_MIN_PAYOUT else
                     f"可持续内生增长 {sustainable_g:.1%} > 永续上限 {PERPETUAL_G_CAP:.1%}"
                     f"（单阶段 Gordon 会结构性低估），仅作对照"))
            card["band_sensitivity"] = (
                f"A-1 股东回报口径：{sr['year']} 年现金分红 {sr['cash']/1e8:.1f}亿 + 回购注销率 "
                f"{sr['cancel_rate']:.2%} = 可分配现金 {distributable/1e8:.1f}亿；g={growth:.2%}"
                f"（分红率 {payout:.0%}，{gate}）→ 带 {a1_low:.4g}~{a1_high:.4g}；A-2 带中值 {a2_mid:.4g}。")
            if a2_mid and abs(a1_mid / a2_mid - 1) > A1_A2_DIVERGENCE:
                card["band_fragile"] = "true"
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
                basis = (f"A-1（与 A-2 取孰低，本行 A-1 更低）：可分配现金 {distributable/1e8:.1f}亿"
                         f"（{sr['year']} 现金分红 + 回购注销）÷ (r {A1_REQUIRED_RETURN:.1%} − g {growth:.2%})"
                         f" × 分层系数 [{low_coef}, {high_coef}]")
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
                    revenue = ttm(periods, "TOTALOPERATEREVE")
                    pe_med = band.get("pe_ttm_median")
                    current_margin = (profit_ttm / revenue * 100) if revenue else None
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
            card["band_is_floor"] = "true"   # 窗口后增长不入 base 带，按 §6.5.6 期权补
            basis = (f"{year}E 正常化归母中位数 {anchor/1e8:.2f}亿（{count} 家覆盖）× {multiple} "
                     f"= 现值口径；{pv_note}。**窗口后增长不计入 base 带**，为下限")
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
            profit = ttm(periods, "PARENTNETPROFIT")
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
                if abs((low + high) / 2 / ((k2_profit / 1e8 * k2_pe * (k2_lo + k2_hi) / 2 / shares)) - 1) > A1_A2_DIVERGENCE:
                    card["band_fragile"] = "true"
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
            extra = card.get("band_sensitivity") or ""
            card["band_sensitivity"] = (f"锚±15% → 带 {sens_low:.4g}~{sens_high:.4g}"
                                        f"（基准 {low:.4g}~{high:.4g}）；"
                                        + share_count_check(evidence, shares)
                                        + (f"｜{extra}" if extra else "")
                                        + (f"｜{sr_note}" if sr_note else "")
                                        + (f"｜{card.get('cycle_note') or ''}" if card.get("cycle_note") else ""))
    elif not card["note"] and not card["needs_external"]:
        card["note"] = "锚定量或倍数取数失败，须人工补"

    return card


def main() -> int:
    parser = argparse.ArgumentParser(description="按 §6.5.2.1 口径计算建带卡草稿")
    parser.add_argument("--tags", type=Path, required=True, help="CSV: security_code,strategy_tag_letter")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()

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
    print(f"  输出：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
