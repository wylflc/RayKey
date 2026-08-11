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

五个已实测到的坑（都不是假想，全池里全部真实出现过）
--------------------------------------------------
1. **公告日不单调**。九号公司 2019 年各期是上市时补披露的：`2019-12-31` 公告于
   2020-06-03，却早于 `2019-06-30` 的 2020-09-30。故「某天该用哪条带」**不能**按报告期
   顺序取，必须取「所有 `available_at ≤ 当日` 的带里报告期最新的那条」。

2. **TTM 需要三期，而三期的公告日不一定都早于本期公告日**。TTM(Q1) = Q1 + 上年报 −
   上年 Q1，而年报常与一季报同期披露（甚至更晚）。故本脚本的生效日取
   **`available_at = max(所用各期的公告日)`**，不是本期公告日——否则就是 §12.4 前视。

3. **`weightavg_roe = 0` 是缺失值伪装成数字**。九号公司 2019 年报净利 −4.5 亿、ROE 却
   写 0。凡净利非零而 ROE 恰为 0 一律当缺失（§15.2 第 3 条：静默失效已复发五次）。

4. **不复权价 × 送转 = 带与价不同基**，且基准日是**公告日不是报告期末**。亿联网络
   `2019-06-30` 报告公告于除权之后、BPS 由 12.46 直降 6.25，按期末起算会再除一次。

5. **报告期早于首个交易日的带，其每股口径是上市前的**。IPO 发行同时抬高净资产与股本，
   而这笔发行**不在除权除息表里**，`split_factor` 抓不到。实测柏楚电子上市首段用
   `2019-06-30` 报告（发行前 BPS 5.45）对上市后价格，P/V 报 3.49，待首个上市后报告落地
   立刻变 0.47——**3.85 倍的假跳空**。故这类带一律不许参与定价。

口径选择（**这些是判断，不是数据，需用户确认**）
----------------------------------------------
* `--r-mode tier`（缺省）：`r` 按 §6.5.7.1 分档中位 L1 8%／L2 10%／L3 13%，`ROE_T` 按
  档位表。**已知问题见 §6.5.7.1.1**——它把质量惩罚写进 `r`，与 §6.2.1 的买入规则重复
  惩罚同一风险，实测制造出按档位分层的 2.6 倍价差。
* `--r-mode market`：`r = R_f + β·ERP` 逐期取值，`ROE_T = r + 永续超额`，
  **且 `g_T` 被 `R_f` 封顶**。风险惩罚移交决策层 `MOS_BY_TIER`。
  **`g_T ≤ R_f` 必须与降 r 同时生效**：实测只降 r 不动 g_T 会使 P0* +109%，捆绑后 +75%。
  利率序列见 §12.4.4（200 行月末观测，2010-2026）。**某期无当时可观测的利率即拒绝该带，
  不外推、不借用后来的利率**——用今天的利率回测七年前属 §12.4 前视。
* `g_T` 缺省 3%（market 模式下再取 `min(3%, R_f)`），`N` = 10 年线性 fade。
* **`N=10` 是衰减期不是高增长期**：§6.5.7.1 v1.56 硬规则限制的 `n1` 是「增速维持不变的
  年数」，本模型 g 自第 1 年即开始衰减，`n1` 实为 0，故不与该规则冲突。
* `roe0` 缺省走「长期锚 + 趋势识别 + 近期读数」（`trend_aware_roe`），不是纯中位。
* `g0` 两种口径都算，默认用哪个见 `--g0-source`：
  - `trailing`：归母净利 TTM 的三年 CAGR。**是外推**（§15.2 第 6 条的形态之一）。
  - `sustainable`：`roe0 × (1 − 近三年派息率均值)`，即可内生维持的增长。**不外推**，
    且与模型的再投资关系自洽。
* `incremental_roe = ΔEPS/ΔBPS` **只报不用**：全池实测 **56%** 的带其增量回报低于建模
  ROE（中位低 2.0pp），即 `g = ROE×b` 多数情况下高估增长。是否接入模型待裁定。
* **两条终值护栏（全池铺开时才暴露，样本里看不到）**：①`ROE_T` 不得高于 `ROE0`——本模型的
  fade 是「竞争侵蚀」不是「困境反转」，把 `ROE_T=r+超额` 套到低谷公司等于凭空假设复苏
  （中国船舶 2019 各期 ROE0 仅 0.24%，曾据此算出隐含 PE **391**）；②`ROE_T` 须高出 `g_T`
  至少 `--min-terminal-spread`（缺省 2pp）——逼近时派息率 `1−g_T/ROE_T` 趋零、估值对分母
  任意敏感（芒果超媒 2017-09-30 算出 0.60，下期资产注入后变 27.32，**45 倍跳变**）。
  两条都命中的公司会被拒，**正确地转去 §6.5.5.2 逐票建档**。

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
    cost_of_equity,
    intrinsic_value,
    margin_of_safety,
    terminal_growth_ceiling,
    terminal_roe,
    valuation_label,
)

FIN_DIR = ROOT / "data/raw/financials"
OHLCV_DIR = ROOT / "data/raw/ohlcv"
ACTIONS = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"
TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"

# §6.5.7.2：现值锚已含要求回报，系数取 [0.90, 1.10] 而非 [0.85, 1.05]（避免二次保守）。
BAND_LOW_COEF, BAND_HIGH_COEF = 0.90, 1.10

# --------------------------------------------------------- r 与终值参数
#
# 两套口径并存，由 `--r-mode` 选：
#
# `tier`（旧）：§6.5.7.1 的质量分档区间取中位。**已知问题**——它把「公司差、多要点回报」
#   写进 r，而 §6.2.1 的档位买入规则又惩罚一次同一个风险，构成重复惩罚；且 L3 的 13%
#   对应的是极高风险企业，不该因为只是「战术层」就自动赋值。
#
# `market`（新，2026-08-08 外部评审建议）：`r = R_f + β·ERP`，逐期取当时的 R_f 与 ERP。
#   风险惩罚改由**决策层的安全边际**承担（`MOS_BY_TIER`），与估值层分离。
TIER_PARAMS = {
    "L1": {"r": 0.08, "roe_terminal": 0.15},
    "L2": {"r": 0.10, "roe_terminal": 0.12},
    "L3": {"r": 0.13, "roe_terminal": 0.10},
}
DEFAULT_TIER = "L2"

RATES_FILE = ROOT / "data/reference/cost_of_equity_inputs.csv"

# β 初版按类型简化（评审给的量级）。**不用行情 raw beta**：小盘噪声、停牌、A 股风格切换
# 都会让它失真，且过去的 β 未必代表未来。待有行业 β 后再按资本结构还原。
BETA_BY_TIER = {"L1": 0.9, "L2": 1.0, "L3": 1.3}

# 终值超额回报 `ROE_T − r`。竞争均衡下增量回报趋向资本成本，故无护城河者取 0
# （此时终值 PE 恰为 1/r，增长不创造价值）。正超额是**需要护城河证据**的强假设。
TERMINAL_EXCESS_BY_TIER = {"L1": 0.06, "L2": 0.03, "L3": 0.0}

# 安全边际属决策层，**不得再塞进 r**（否则与 §6.2.1 档位规则重复惩罚同一风险）。
MOS_BY_TIER = {"L1": 0.10, "L2": 0.20, "L3": 0.30}


def load_rates() -> list[tuple[str, float, float]]:
    """(观测日, R_f, ERP) 升序。逐期取值以避免用 2026 年的利率回测 2017 年。"""
    if not RATES_FILE.exists():
        return []
    rows = []
    with RATES_FILE.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rf, erp = _num(row.get("risk_free_rate")), _num(row.get("equity_risk_premium"))
            if rf is not None and erp is not None:
                rows.append((row["observed_on"], rf, erp))
    return sorted(rows)


def rates_as_of(rates: list[tuple[str, float, float]], date: str) -> tuple[float, float] | None:
    """`date` 当时**已可观测**的最近一组利率；无则 None——**不外推、不用后来的利率**。"""
    usable = [x for x in rates if x[0] <= date]
    return (usable[-1][1], usable[-1][2]) if usable else None

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


def annual_roe_series(series: dict[str, dict], available_at: str, years: int) -> list[tuple[str, float]]:
    """公告日 ≤ `available_at` 的近 `years` 个财年 ROE，**按财年升序**。"""
    out = []
    for period in reversed(fiscal_years_before(series, available_at, years)):
        row = series[period]
        roe, profit = _num(row.get("weightavg_roe")), _num(row.get("parent_netprofit"))
        if roe is None or (roe == 0 and profit not in (None, 0)):
            continue
        out.append((period, roe / 100.0))
    return out


def net_margin(row: dict) -> float | None:
    profit, revenue = _num(row.get("parent_netprofit")), _num(row.get("total_operate_income"))
    if profit is None or not revenue:
        return None
    return profit / revenue


def trend_efficiency(values: list[float]) -> float:
    """净变动 ÷ 总行程，∈[0,1]。**单调趋势趋近 1，来回震荡趋近 0。**

    为什么不用标准差判周期股（首版即用 σ，实测是错的）：σ 量的是**离散度**，而一路上行的
    成长股离散度同样很大。实测宁德时代 σ=39.4%、亿联网络 18.8%（都是趋势不是周期），
    而真正的商品周期股紫金矿业只有 6.7%、徐工机械 5.1%——**按 σ 判会把两类正好判反**。
    本比率量的是「有没有来回」，才是周期的定义。
    """
    if len(values) < 3:
        return 1.0
    travel = sum(abs(b - a) for a, b in zip(values, values[1:]))
    return abs(values[-1] - values[0]) / travel if travel else 1.0


def roe_trend(series: dict[str, dict], observations: list[tuple[str, float]],
              min_efficiency: float) -> str:
    """判定 ROE 是否存在**可靠**趋势，返回 "up"／"down"／""。

    两条都要满足，缺一即判无趋势：
    ① 走势够单调（`trend_efficiency ≥ 阈值`）——比「三次变化里两次同向」严得多，后者约有
       一半概率靠掷硬币就能满足；
    ② **净利率同向**——这是用现有字段能做的那一半杜邦验证。ROE 上行若并非来自净利率改善，
       就可能只是净资产被回购／减值做小了，那不是经营能力提高，不该据此上调估值。
       （完整杜邦还需资产周转率与权益乘数，本表无总资产字段，故只做这一半并写明。）
    """
    if len(observations) < 4:
        return ""
    values = [v for _, v in observations]
    if trend_efficiency(values) < min_efficiency:
        return ""
    direction = "up" if values[-1] > values[0] else "down"
    margins = [m for m in (net_margin(series[p]) for p, _ in observations) if m is not None]
    if len(margins) < 2:
        return ""
    return direction if ((margins[-1] > margins[0]) == (direction == "up")) else ""


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


# 走势单调度阈值。低于下限 = 来回震荡 = 周期股，窗口拉长到覆盖一个完整景气周期；
# 高于上限 = 结构性趋势，近期读数才有资格加权。中间地带一律当无趋势，用锚。
CYCLICAL_EFFICIENCY = 0.35
CYCLICAL_AMPLITUDE = 0.50        # ROE 极差须超过中位数一半，否则只是平稳带噪声
TREND_EFFICIENCY = 0.55
CYCLICAL_WINDOW = 9              # 周期股窗口须覆盖一个完整景气周期，5 年可能只覆盖半个


def growth_confirmed(series: dict[str, dict], observations: list[tuple[str, float]]) -> bool:
    """确认成长：ROE **连续两年上行** 且 净利率同向 且 营收同向。三条缺一不可。

    比 `roe_trend` 严格——后者只要求整段走势单调度够高与净利率同向，可能命中一次性跳升；
    此处要求最近两次年度变化都为正，且营收也在扩张，以排除「减值做小净资产」与
    「毛利改善但规模萎缩」两类假成长。**全部只用已披露年报，无前视。**
    """
    if len(observations) < 3:
        return False
    values = [v for _, v in observations]
    if not (values[-1] > values[-2] > values[-3]):
        return False
    margins = [net_margin(series[p]) for p, _ in observations[-3:]]
    revenues = [_num(series[p].get('total_operate_income')) for p, _ in observations[-3:]]
    if any(m is None for m in margins) or any(r is None for r in revenues):
        return False
    return margins[-1] > margins[0] and revenues[-1] > revenues[0]


def trend_aware_roe(series: dict[str, dict], available_at: str, base_years: int,
                    stat: str, latest_weight: float = 0.6,
                    recent_weight: float = 0.6) -> tuple[float | None, dict]:
    """长期锚 + 趋势识别 + 近期读数的混合 ROE（2026-08-08 外部评审建议，实测后采纳）。

    为什么不在「TTM」与「五年中位」之间二选一：中位数能治**噪声与周期**，治不了**结构性趋势**。
    实测两端都有代价——TTM 口径下东阿阿胶 2020 年低谷算出隐含 PE **201**（恰在底部报最贵）；
    纯五年中位下九号公司（ROE 上行）对人工档案只有 **0.20x**、山西汾酒（ROE 下行）**2.04x**。

    故：无可靠趋势时用锚（中位）；有可靠趋势时按 `0.6·近期 + 0.4·锚` 让近期读数说话。
    「可靠」的判据见 `roe_trend`——**必须同时有净利率的同向印证**，否则回购做小净资产
    造成的 ROE 上行也会被当成经营改善。
    """
    probe = [v for _, v in annual_roe_series(series, available_at, max(base_years, CYCLICAL_WINDOW))]
    efficiency = trend_efficiency(probe)
    # 判周期股要**两个条件**：来回震荡（低单调度）**且**振幅够大。只看单调度会把「平稳带
    # 小噪声」也判成周期——实测贵州茅台单调度仅 32%（净变动小、行程也小），但 ROE 常年
    # 30~38%，显然不是周期股。故加振幅闸：极差须超过中位数的一半。
    amplitude = (max(probe) - min(probe)) / abs(statistics.median(probe)) if probe and statistics.median(probe) else 0.0
    cyclical = efficiency < CYCLICAL_EFFICIENCY and amplitude > CYCLICAL_AMPLITUDE
    window = CYCLICAL_WINDOW if cyclical else base_years

    observations = annual_roe_series(series, available_at, window)
    if not observations:
        return None, {"years": 0}
    values = [v for _, v in observations]
    agg = statistics.median if stat == "median" else statistics.fmean
    anchor = agg(values)
    direction = roe_trend(series, observations, TREND_EFFICIENCY)
    confirmed = growth_confirmed(series, observations) if direction == "up" else False
    if direction and len(values) >= 2:
        # 两层阻尼：①`recent` 把最新一年与上一年混合；②再与长期锚混合。
        # **对确认成长股这两层会叠加成六四折**——实测中际旭创 2024 年 ROE 31.23%，
        # 经 0.6×(0.6×31.23+0.4×16.58)+0.4×11.73 后只剩 19.91%，内在价值随之腰斩，
        # 该股在 2025 年 4 月（前瞻 PE 约 7）仍被合格线 P/V≤0.90 挡在门外（用户 2026-08-09 指出）。
        # `growth_confirmed` 命中时改用更陡的权重，让已实现的最新一年说话。
        w_last = latest_weight if confirmed else 0.6
        w_recent = recent_weight if confirmed else 0.6
        recent = w_last * values[-1] + (1 - w_last) * values[-2]
        value = w_recent * recent + (1 - w_recent) * anchor
    else:
        value = anchor
    return value, {"years": len(values), "window": window, "anchor": anchor,
                   "trend": direction, "roe_sigma": efficiency,
                   "growth_confirmed": "1" if confirmed else ""}


# 单边归一化口径：**只在一个方向上放弃归一化**（用户 2026-08-11 指令）。
# 动机是横截面实测——今日池里当期 ROE 站上自身五年中位 115% 的 49 只，只有 1 只过得了
# 买入线；而归一化真正要防的只是「在周期低谷把低盈利外推十年」这一个方向。两个方向用
# 同一把尺子，等于为了防低谷陷阱把结构性改善一并抹掉。
ONESIDED_SOURCES = ("onesided_up", "onesided_max", "onesided_min")


def pick_roe0(mode: str, normalized: float, roe_ttm_value: float | None,
              trend: str) -> tuple[float, str]:
    """单边口径下本行取哪一侧的 ROE，返回 (roe0, 口径标签)。

    **比较基准是 `trend_aware_roe` 的输出（= `normalized` 臂实际用的 roe0），不是纯五年中位。**
    趋势成立时前者已是「0.36 最新年 + 0.24 上年 + 0.40 中位」的混合值；拿纯中位去比就变成了
    另一条规则，且与 `normalized` 臂不再构成单变量对照。两者逐行分列 `roe0_normalized`
    与 `roe_anchor`，可事后复核。

    * `onesided_up`——**只对判定为上行趋势的行**改用当期 TTM ROE，其余不动。
      判据沿用 `roe_trend`（单调度 + 净利率同向印证），不另立标准；这是最窄的一刀。
    * `onesided_max`——当期高于归一化值就取当期，即**保留低谷保护、去掉高位惩罚**。
    * `onesided_min`——当期低于归一化值就取当期，即 §12.14 末尾提的「取两者孰低」。**它是对照组**：
      与前两者方向相反，若三者同向变好则说明是尺度效应而非方向信息。

    `roe_ttm` 取不到时一律回落到归一化值，并在标签里写明——**不得静默回落**（§13 第 3 条）。
    """
    if roe_ttm_value is None:
        return normalized, "normalized(无TTM)"
    if mode == "onesided_up":
        return (roe_ttm_value, "ttm(上行)") if trend == "up" else (normalized, "normalized")
    if mode == "onesided_max" and roe_ttm_value > normalized:
        return roe_ttm_value, "ttm(孰高)"
    if mode == "onesided_min" and roe_ttm_value < normalized:
        return roe_ttm_value, "ttm(孰低)"
    return normalized, "normalized"


def incremental_roe(series: dict[str, dict], actions: list[dict], available_at: str,
                    span: int = 4) -> float | None:
    """增量股东回报 `ΔEPS / ΔBPS`——**新投进去的一块钱赚回多少**。

    为什么必须单看它（外部评审 2026-08-08 提出，本仓库现有字段刚好够算）：
    `g = ROE × b` 隐含「新增资本能继续赚到与存量相同的 ROE」，这对多数非金融公司不成立。
    茅台过去 ROE 35%，不代表新投 100 亿还能产出 35 亿。真正决定增长的是**增量回报**，
    历史平均 ROE 只是它的一个有偏代理。

    两期的每股口径若跨过送转并不同基，故按公告日之间的累计送转比把旧期折算回来再相减。
    """
    annuals = fiscal_years_before(series, available_at, span + 1)
    if len(annuals) < span + 1:
        return None
    new_period, old_period = annuals[0], annuals[-1]
    new_row, old_row = series[new_period], series[old_period]
    factor = split_factor(actions, old_row["notice_date"], new_row["notice_date"])
    eps_new, eps_old = _num(new_row.get("basic_eps")), _num(old_row.get("basic_eps"))
    bps_new, bps_old = _num(new_row.get("bps")), _num(old_row.get("bps"))
    if None in (eps_new, eps_old, bps_new, bps_old):
        return None
    delta_eps = eps_new - eps_old / factor
    delta_bps = bps_new - bps_old / factor
    if delta_bps <= 0:
        return None   # 净资产未增长时增量回报无定义（回购／分红超过留存）
    return delta_eps / delta_bps


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
    r_mode: str = ""
    rf: float | None = None
    erp: float | None = None
    beta: float | None = None
    g_terminal: float | None = None
    roe_terminal: float | None = None
    roe_anchor: float | None = None
    roe_trend: str = ""
    # 单边口径的两个留痕列。**`roe0_normalized` 不是 `roe_anchor`**：前者是 `trend_aware_roe`
    # 的输出（趋势成立时已是「0.36 最新年 + 0.24 上年 + 0.40 中位」的混合值），后者是纯中位。
    # 单边口径比的是**现行归一化结果**与当期，故必须单独留一列，否则事后无法逐行复核取了哪侧。
    roe0_normalized: float | None = None
    roe0_mode: str = ""            # 本行实际取了哪一侧（normalized / ttm）
    roe_window: int | None = None
    roe_sigma: float | None = None
    incremental_roe: float | None = None
    mos: float | None = None
    max_buy_price: float | None = None
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
    elif args.roe_source in ONESIDED_SOURCES and eps is not None and roe is not None:
        # 单边口径**读 TTM ROE 来定取哪一侧**，故 TTM 各分量的公告日同样进生效日——
        # 只在最终取了 TTM 那一侧才结转，就是拿后来才披露的数做了当期的选择（§12.4 前视）。
        evidence += eps.evidence_dates + roe.evidence_dates
    available_at = max(evidence)

    params = TIER_PARAMS.get(tier, TIER_PARAMS[DEFAULT_TIER])
    rf = erp = beta = None
    g_terminal = args.g_terminal
    if args.r_mode == "market":
        observed = rates_as_of(args.rates, available_at)
        if observed is None:
            return Band(code, name, period, notice, available_at, "unavailable",
                        f"{available_at} 当时无可观测的 R_f/ERP —— **不外推、不借用后来的利率**"
                        f"（§12.4）；须补 {RATES_FILE.name} 的历史序列")
        rf, erp = observed
        beta = BETA_BY_TIER.get(tier, 1.0)
        r = cost_of_equity(rf, erp, beta)
        # 终值 ROE 由 r 推出而非拍档位表：竞争均衡下增量回报趋向资本成本。
        roe_t = terminal_roe(r, TERMINAL_EXCESS_BY_TIER.get(tier, 0.0))
        # **g_T ≤ R_f 与「r 用 R_f+βERP」是一套，不能只取前半**。R_f 已含长期通胀与实际
        # 增长预期，g_T > R_f 等于假设经济永续跑赢无风险利率。实测只降 r 不动 g_T，
        # P0* 由 10.19 抬到 21.29（+109%）；同时收紧 g_T 则为 17.88（+75%）——
        # 差额的三分之一来自这个未经检验的 g_T 而非来自 r。
        g_terminal = min(args.g_terminal, terminal_growth_ceiling(rf))
    else:
        r, roe_t = params["r"], params["roe_terminal"]

    band = Band(code, name, period, notice, available_at, "unavailable",
                eps_ttm=eps.value if eps else None, roe_ttm=roe.value if roe else None,
                roe_source=roe_source, bps=bps,
                g_trailing=trailing_cagr(series, period), r=r, r_mode=args.r_mode,
                rf=rf, erp=erp, beta=beta, g_terminal=g_terminal, roe_terminal=roe_t,
                mos=MOS_BY_TIER.get(tier),
                incremental_roe=incremental_roe(series, actions, available_at))

    # 归一化口径：ROE 取近五年年度中位（结构参数），EPS 由清洁盈余 E = ROE×B 反推。
    # 这样两个输入天然自洽，且不把周期低谷的读数外推十年（见 normalized_roe 文档）。
    if args.roe_source == "ttm":
        roe0, eps0 = roe.value, eps.value
        band.roe0_mode = "ttm"
    else:
        roe0, meta = trend_aware_roe(series, available_at, args.roe_years, args.roe_stat,
                                     args.growth_latest_weight, args.growth_recent_weight)
        band.roe_anchor = meta.get("anchor")
        band.roe_trend = meta.get("trend", "")
        band.roe_window = meta.get("window")
        band.roe_sigma = meta.get("roe_sigma")
        if roe0 is None or bps is None or bps <= 0:
            band.reason = ("归一化 ROE 不可算：无已披露年报 ROE" if roe0 is None else
                           f"BPS={bps} 不可用")
            return band
        if meta["years"] < args.min_roe_years:
            band.reason = f"已披露年报 ROE 仅 {meta['years']} 年 < 要求 {args.min_roe_years} 年"
            return band
        band.roe0_normalized, band.roe0_mode = roe0, "normalized"
        if args.roe_source in ONESIDED_SOURCES:
            roe0, band.roe0_mode = pick_roe0(args.roe_source, roe0,
                                             roe.value if roe else None, band.roe_trend)
        # **eps0 一律走清洁盈余 `E = ROE×B`**，与 normalized 臂同式——单边口径改的只有
        # 「roe0 取哪一侧」这一个自由度，若同时换 EPS 口径就分不清差异来自哪一处。
        eps0 = roe0 * bps
    band.roe0, band.eps0 = roe0, eps0

    # **终值 ROE 不得高于起始 ROE**：本模型的 fade 是「竞争侵蚀超额回报」的衰减机制，
    # 不是「困境反转」的复苏机制。把 `ROE_T = r + 超额` 硬套到低谷公司上，等于凭空假设它
    # 回升到行业均值——实测中国船舶 2019 各期 ROE0 仅 **0.24%**、终值被设为约 10%，
    # 模型据此算出隐含 PE **391**，价值全部来自那个没有证据的复苏假设。
    # 压到 `min(ROE_T, ROE0)` 后，这类公司多半会被下面的 `ROE_T > g_T` 护栏拦掉，
    # **正确地转去 §6.5.5.2 逐票建档**——低谷反转本就不该由批量模型定价。
    roe_t = min(roe_t, roe0) if roe0 > 0 else roe_t
    band.roe_terminal = roe_t

    # 终值 ROE 逼近 g_T 时派息率 `1 − g_T/ROE_T` 趋于 0，价值对分母**任意敏感**——不是
    # 「便宜」而是「算不出」。现有护栏只拦 `ROE_T ≤ g_T`，差一点点却照算，实测芒果超媒
    # 2017-09-30（roe0 3.80%、g_T 3.00%）算出内在值 0.60，下一期 ROE 因资产注入跳到
    # 18.33%、内在值变 27.32——**45 倍的换带跳变**。故要求留出实打实的利差。
    if roe0 > 0 and roe_t < g_terminal + args.min_terminal_spread:
        band.status = "rejected"
        band.reason = (f"ROE_T={roe_t:.2%} 距 g_T={g_terminal:.2%} 不足 "
                       f"{args.min_terminal_spread:.1%}：可分配现金趋零、估值对分母任意敏感，"
                       f"须走 §6.5.5.2 逐票建档")
        return band

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

    # `trailing_fb`（用户 2026-08-10，修 §12.9.7 结论三的混淆②）：优先用已实现三年 CAGR，
    # **取不到时回落到 sustainable**。纯 `trailing` 会丢掉 2,793 条带（19.8% 覆盖），
    # 而 `g_trailing` 是 `g_sustainable` 的严格子集，回落即可补齐、不引入新缺口。
    if args.g0_source == "trailing":
        g0 = band.g_trailing
    elif args.g0_source == "trailing_fb":
        g0 = band.g_trailing if band.g_trailing is not None else band.g_sustainable
    else:
        g0 = band.g_sustainable
    # `--g0-shrink`（用户 2026-08-10）：g0 乘数。**用来检验「该资本化多少增长」这一整条响应曲线**，
    # 而不是逐条修补输入。动机是 `incremental_roe`（ΔEPS/ΔBPS）实测中位 13.2% 低于建模 roe0 16.1%
    # （−3.3pp、59% 偏低），即 `g = ROE×b` 多数情况下高估增长；但它本身噪声过大不能直接当输入
    # （P5 −19.8%、P95 52.5%、17% 为负），故改用可控乘数等价检验。1.0 = 原行为。
    if g0 is not None and args.g0_shrink != 1.0:
        g0 *= args.g0_shrink
    if g0 is None:
        band.reason = f"g0（{args.g0_source}）不可算：近三年无正 EPS 财年可算派息率"
        return band

    g0 = max(g0, args.g0_floor)
    if g0 > args.g0_cap:
        g0, band.g0_capped = args.g0_cap, True
    band.g0 = g0

    try:
        result = intrinsic_value(eps0, roe0, g0, r, roe_terminal=roe_t,
                                 g_terminal=g_terminal, n=args.n, n1=args.n1)
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
    # 安全边际在**决策层**单独给出，不混进 r（否则同一个风险被惩罚两次）
    if band.mos is not None:
        band.max_buy_price = margin_of_safety(result.intrinsic_value, band.mos)
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
    # 坑 5：**报告期早于首个交易日的带，其每股口径是上市前的**（IPO 发行使净资产与股本
    # 同时跳升，而这笔发行不在除权除息表里，故 `split_factor` 抓不到）。实测柏楚电子
    # 上市首段用 `2019-06-30` 报告（发行前 BPS 5.45）对上市后价格，P/V 报 3.49；
    # 待首个上市后报告落地立刻变 0.47——**3.85 倍的假跳空**。故直接不许这类带参与定价。
    first_traded = prices[0][0]
    usable = [b for b in usable if b.report_date >= first_traded]
    if not usable:
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
               "eps0", "roe0", "roe_anchor", "roe_trend", "roe0_normalized", "roe0_mode",
               "growth_confirmed", "roe_window", "roe_efficiency",
               "incremental_roe", "payout", "g_trailing", "g_sustainable", "g0", "g0_capped",
               "r_mode", "rf", "erp", "beta", "r", "g_terminal", "roe_terminal",
               "intrinsic_value", "band_low", "band_high", "mos", "max_buy_price",
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
        "eps0": fmt(band.eps0), "roe0": fmt(band.roe0),
        "roe_anchor": fmt(band.roe_anchor), "roe_trend": band.roe_trend,
        "roe0_normalized": fmt(band.roe0_normalized, 6), "roe0_mode": band.roe0_mode,
        "roe_window": "" if band.roe_window is None else str(band.roe_window),
        "roe_efficiency": fmt(band.roe_sigma), "incremental_roe": fmt(band.incremental_roe),
        "payout": fmt(band.payout),
        "g_trailing": fmt(band.g_trailing), "g_sustainable": fmt(band.g_sustainable),
        "g0": fmt(band.g0), "g0_capped": "Y" if band.g0_capped else "",
        "r_mode": band.r_mode, "rf": fmt(band.rf, 4), "erp": fmt(band.erp, 4),
        "beta": fmt(band.beta, 2), "r": fmt(band.r, 4),
        "g_terminal": fmt(band.g_terminal, 4), "roe_terminal": fmt(band.roe_terminal, 4),
        "mos": fmt(band.mos, 2), "max_buy_price": fmt(band.max_buy_price),
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

    if ok:
        trends: dict[str, int] = defaultdict(int)
        for band in ok:
            trends[band.roe_trend or "无趋势→用锚"] += 1
        print("ROE 趋势判定（净利率同向印证后）：" + "｜".join(f"{k} {v}" for k, v in sorted(trends.items())))
        cyc = [b for b in ok if b.roe_window and b.roe_window > args.roe_years]
        print(f"按周期股拉长窗口（走势单调度<{CYCLICAL_EFFICIENCY:.0%}）：{len(cyc)}/{len(ok)}"
              f"（{len(cyc)/len(ok):.0%}）")
        pairs = [(b.incremental_roe, b.roe0) for b in ok if b.incremental_roe is not None and b.roe0]
        if pairs:
            gaps = sorted(inc - roe for inc, roe in pairs)
            below = sum(1 for inc, roe in pairs if inc < roe)
            print(f"增量 ROE(ΔEPS/ΔBPS) − 建模 ROE（n={len(pairs)}）：中位 {statistics.median(gaps):+.1%}｜"
                  f"**低于建模 ROE 的有 {below}（{below/len(pairs):.0%}）**"
                  f"\n  ↑ 低于即说明「新投入的钱赚得不如存量」，g=ROE×b 会高估增长（外部评审第 11 点）")

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
    per_stock: dict[str, list[Band]] = defaultdict(list)
    names: dict[str, str] = {}
    for code, band in all_bands:
        per_stock[code].append(band)
        names[code] = band.name

    def line(code: str) -> str:
        group = per_stock[code]
        good = sum(1 for b in group if b.status == "ok")
        days, in_scope = daily_counts.get(code, 0), price_counts.get(code, 0)
        cover = f"{days}/{in_scope}（{days/in_scope:.0%}）" if in_scope else "无可用区间"
        mark = "" if good else "   ← **一条带都没建成**"
        return f"  {code} {names[code]:<8} {good:>2}/{len(group):<3} → {cover}{mark}"

    # 261 只时逐股列 261 行没人会看，只列**有问题的**；全通过也要明说，否则「查过了没问题」
    # 与「压根没查」在报告上长得一样（§15.2 第 3 条）。
    def broken(code: str) -> bool:
        group = per_stock[code]
        good = sum(1 for b in group if b.status == "ok")
        days, in_scope = daily_counts.get(code, 0), price_counts.get(code, 0)
        return good == 0 or good < 0.6 * len(group) or (in_scope and days < in_scope)

    problems = [c for c in sorted(per_stock) if broken(c)]
    if len(per_stock) > 30:
        print(f"\n逐股覆盖：{len(per_stock)} 只中 **{len(per_stock) - len(problems)} 只无异常**"
              f"（建带率 ≥60% 且生效后逐日 100% 有状态）")
        if problems:
            print(f"以下 {len(problems)} 只须看（成功带数/报告期数 → 首带生效后有状态交易日/该区间交易日）：")
            for code in problems:
                print(line(code))
    else:
        print("\n逐股覆盖（成功带数 / 报告期数 → 首带生效后有状态交易日 / 该区间交易日）：")
        for code in sorted(per_stock):
            print(line(code))


def main() -> int:
    parser = argparse.ArgumentParser(description="历史估值带重建（OI-034 第 1 步）")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--sample", action="store_true", help="10 只可行性验证样本")
    scope.add_argument("--codes", help="逗号分隔代码")
    scope.add_argument("--all", action="store_true", help="全部有行情的股票")
    scope.add_argument("--codes-file", type=Path, help="每行一个代码")
    parser.add_argument("--since", default="2016-03-31")
    # 时点股票库回测**必须**用它。否则池内 261 只带着 §5 人工分档（L1 终值超额 6%），
    # 池外 1,278 只一律落 DEFAULT_TIER（3%）——选样偏差会绕过可选池、从估值口径溜回来。
    parser.add_argument("--uniform-tier", choices=tuple(TIER_PARAMS),
                        help="强制所有股票用同一分档，抹掉人工分档带来的前视优势")
    parser.add_argument("--roe-source",
                        choices=("normalized", "ttm") + ONESIDED_SOURCES, default="normalized",
                        help="normalized=近五年年度 ROE 中位并由 E=ROE×B 反推 EPS（缺省，避免顺周期陷阱）；"
                             "onesided_up/max/min=单边归一化，见 pick_roe0")
    parser.add_argument("--g0-source", choices=("sustainable", "trailing", "trailing_fb"),
                        default="sustainable",
                        help="trailing_fb = 优先已实现三年 CAGR、取不到时回落 sustainable（补齐覆盖）")
    parser.add_argument("--r-mode", choices=("tier", "market"), default="tier",
                        help="tier=§6.5.7.1 分档中位（旧）；market=R_f+βERP 逐期取值（需利率序列）")
    parser.add_argument("--roe-years", type=int, default=5, help="归一化 ROE 的回看年数")
    parser.add_argument("--roe-stat", choices=("median", "mean"), default="median")
    parser.add_argument("--min-roe-years", type=int, default=3,
                        help="归一化 ROE 至少需要几个已披露财年，缺省 3")
    parser.add_argument("--growth-latest-weight", type=float, default=0.6,
                        help="确认成长股：最新一年在 recent 中的权重（缺省 0.6 即不变）")
    parser.add_argument("--growth-recent-weight", type=float, default=0.6,
                        help="确认成长股：recent 相对长期锚的权重（缺省 0.6 即不变）")
    parser.add_argument("--min-terminal-spread", type=float, default=0.02,
                        help="ROE_T 须高出 g_T 的最小利差，缺省 2pp（低于此估值对分母任意敏感）")
    parser.add_argument("--g0-cap", type=float, default=0.25, help="g0 上限，缺省 25%%")
    parser.add_argument("--g0-floor", type=float, default=0.0)
    parser.add_argument("--g0-shrink", type=float, default=1.0,
                        help="g0 乘数，1.0=原行为。用于检验「该资本化多少增长」的响应曲线")
    parser.add_argument("--g-terminal", type=float, default=DEFAULT_G_TERMINAL)
    parser.add_argument("--n", type=int, default=10, help="fade 年数（非高增长年数，见文件头）")
    parser.add_argument("--n1", type=int, default=0,
                        help="高速期年数：前 n1 年 ROE 与 g 维持起始值不衰减，其后再 fade n 年。"
                             "缺省 0 = 原行为（g 自第 1 年即衰减）")
    parser.add_argument("--out-bands", type=Path)
    parser.add_argument("--out-daily", type=Path)
    args = parser.parse_args()

    if args.sample:
        codes = list(SAMPLE_CODES)
    elif args.codes:
        codes = [c.strip().zfill(6) for c in args.codes.split(",") if c.strip()]
    elif args.codes_file:
        codes = sorted({ln.strip().zfill(6) for ln in args.codes_file.read_text().splitlines()
                        if ln.strip()})
    else:
        codes = sorted(p.stem for p in OHLCV_DIR.glob("*.csv"))
    codes = [c for c in codes if not c.startswith("INDEX")]

    args.rates = load_rates()
    if args.r_mode == "market" and not args.rates:
        print(f"**{RATES_FILE.relative_to(ROOT)} 无可用观测**，market 模式无法建带")
        return 1
    tiers = load_tiers()
    financials = load_financials(set(codes))
    actions = load_actions()
    print(f"历史带重建：{len(codes)} 只｜报告期起点 {args.since}｜g0={args.g0_source}"
          + (f"｜**分档统一为 {args.uniform_tier}**" if args.uniform_tier else ""))

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
        tier = args.uniform_tier or (tiers.get(code) or {}).get("quality_tier") or DEFAULT_TIER
        name = next(iter(series.values()))["security_name"]
        periods = sorted(p for p in series if p >= args.since)
        bands = [build_band(code, name, tier, series, actions.get(code, []), p, args) for p in periods]
        all_bands.extend((code, b) for b in bands)
        band_rows.extend(band_row(b, tier) for b in bands)

        prices = load_ohlcv(code)
        states = daily_states(code, bands, prices, actions.get(code, []))
        daily_counts[code] = len(states)
        # 分母须与 `daily_states` 用**同一套**可用带（含坑 5 的上市前口径剔除），否则上市前
        # 那几期被正确剔掉后，覆盖率会被算成「缺了一截」而不是「本就不该有」。
        usable = [b for b in applicable_bands(bands) if prices and b.report_date >= prices[0][0]]
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
