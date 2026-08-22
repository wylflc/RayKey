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
        ↓  scripts/intrinsic_value.py（§6.5.2.2）
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
   **公告日本身先按法定截止日封顶**（`--notice-cap statutory`，缺省，OI-042 建带侧）：东财对 1998-2015
   报告期普遍记成次年同期报告的公告日，不封顶则早年带晚约一年可用、与 2016 年后不同口径。
   **但逐日状态里带的生效日是 `available_at` 之前的最后一个交易日**（`--state-effective prev_trading_day`，
   v4.28 用户裁定）：定期报告在非交易时段披露、官方戳次日，8.31 的公告 8.30 晚上已有，生产扫描在戳日凌晨
   以 as-of=戳日 吸收、用 8.30 收盘出信号、8.31 执行（§6.7）；回测按同一口径，8.30 的状态行即用新带。
   这不是前视——戳日凌晨该公告确已公开；旧口径（`notice`，公告日当天生效）只用于复现 v4.27 前的产物。

3. **`weightavg_roe = 0` 是缺失值伪装成数字**。九号公司 2019 年报净利 −4.5 亿、ROE 却
   写 0。凡净利非零而 ROE 恰为 0 一律当缺失（§13 第 3 条：静默失效已复发五次）。

4. **不复权价 × 送转 = 带与价不同基**，且基准日是**公告日不是报告期末**。亿联网络
   `2019-06-30` 报告公告于除权之后、BPS 由 12.46 直降 6.25，按期末起算会再除一次。

5. **报告期早于首个交易日的带，其每股口径是上市前的**。IPO 发行同时抬高净资产与股本，
   而这笔发行**不在除权除息表里**，`split_factor` 抓不到。实测柏楚电子上市首段用
   `2019-06-30` 报告（发行前 BPS 5.45）对上市后价格，P/V 报 3.49，待首个上市后报告落地
   立刻变 0.47——**3.85 倍的假跳空**。故这类带一律不许参与定价。

口径选择（**这些是判断，不是数据，需用户确认**）
----------------------------------------------
* `--r-mode tier`（缺省）：`r` 按 §6.5.2.1 分档中位 L1 8%／L2 10%／L3 13%，`ROE_T` 按
  档位表。**已知问题见 §6.7**——它把质量惩罚写进 `r`，与 §6.2 的买入规则重复
  惩罚同一风险，实测制造出按档位分层的 2.6 倍价差。
* `--r-mode market`：`r = R_f + β·ERP` 逐期取值，`ROE_T = r + 永续超额`，
  **且 `g_T` 被 `R_f` 封顶**。风险惩罚移交决策层 `MOS_BY_TIER`。
  **`g_T ≤ R_f` 必须与降 r 同时生效**：实测只降 r 不动 g_T 会使 P0* +109%，捆绑后 +75%。
  利率序列见 §12.4.4（200 行月末观测，2010-2026）。**某期无当时可观测的利率即拒绝该带，
  不外推、不借用后来的利率**——用今天的利率回测七年前属 §12.4 前视。
* `g_T` 缺省 3%（market 模式下再取 `min(3%, R_f)`），`N` = 10 年线性 fade。
* **`N=10` 是衰减期不是高增长期**：§6.5.2.1 v1.56 硬规则限制的 `n1` 是「增速维持不变的
  年数」，本模型 g 自第 1 年即开始衰减，`n1` 实为 0，故不与该规则冲突。
* `roe0` 缺省走「长期锚 + 趋势识别 + 近期读数」（`trend_aware_roe`），不是纯中位。
* `g0` 两种口径都算，默认用哪个见 `--g0-source`：
  - `trailing`：归母净利 TTM 的三年 CAGR。**是外推**（§13 第 6 条的形态之一）。
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
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import roic_inputs  # noqa: E402
from disclosure_dates import available_at as statutory_available_at  # noqa: E402

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

# §6.5.2.2：现值锚已含要求回报，系数取 [0.90, 1.10] 而非 [0.85, 1.05]（避免二次保守）。
BAND_LOW_COEF, BAND_HIGH_COEF = 0.90, 1.10

# --------------------------------------------------------- r 与终值参数
#
# 两套口径并存，由 `--r-mode` 选：
#
# `tier`（旧）：§6.5.2.1 的质量分档区间取中位。**已知问题**——它把「公司差、多要点回报」
#   写进 r，而 §6.2 的档位买入规则又惩罚一次同一个风险，构成重复惩罚；且 L3 的 13%
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

# `--roe-external` 装载的外部 ROE 预测：{代码: [(可得日, roe0), ...] 已排序}。
# 缺省为空 dict，即所有既往产出逐位可复现。
EXTERNAL_ROE: dict[str, list[tuple[str, float]]] = {}
EXTERNAL_STATS: defaultdict[str, int] = defaultdict(int)
# `--value-model roic` 的三大报表输入，`main()` 里一次性装载（{代码: {财年: RoicYear}}）
ROIC_YEARS: dict[str, dict[str, "roic_inputs.RoicYear"]] = {}
ROIC_STATS: defaultdict[str, int] = defaultdict(int)

# `--moat-params CSV` 装载的逐票终值/衰减参数覆盖（OI-070 护城河补偿实验，2026-08-20）：
# {代码: {"fade_years": int|None, "terminal_excess": float|None, "n1": int|None}}。
# 缺省为空 dict，即所有既往产出逐位可复现；任何一列留空即沿用全局参数。
MOAT_PARAMS: dict[str, dict[str, float | int | None]] = {}
MOAT_STATS: defaultdict[str, int] = defaultdict(int)

RATES_FILE = ROOT / "data/reference/cost_of_equity_inputs.csv"

# β 初版按类型简化（评审给的量级）。**不用行情 raw beta**：小盘噪声、停牌、A 股风格切换
# 都会让它失真，且过去的 β 未必代表未来。待有行业 β 后再按资本结构还原。
BETA_BY_TIER = {"L1": 0.9, "L2": 1.0, "L3": 1.3}

# 终值超额回报 `ROE_T − r`。竞争均衡下增量回报趋向资本成本，故无护城河者取 0
# （此时终值 PE 恰为 1/r，增长不创造价值）。正超额是**需要护城河证据**的强假设。
TERMINAL_EXCESS_BY_TIER = {"L1": 0.06, "L2": 0.03, "L3": 0.0}

# 安全边际属决策层，**不得再塞进 r**（否则与 §6.2 档位规则重复惩罚同一风险）。
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


def load_financials(codes: set[str] | None, notice_cap: bool = True) -> dict[str, dict[str, dict]]:
    """{代码: {报告期: 行}}。`codes=None` 取全市场。

    读入后应用 `data/reference/financials_corrections.csv` 的订正层（OI-066）：
    源侧确认错误的字段在内存替换，取数产物本身不改（改了会被强制重取覆盖）。

    `notice_cap`（OI-042 建带侧，缺省开）：`notice_date` 在装载时改为可得日
    `min(记录公告日, 法定截止日)`（`disclosure_dates.available_at`，与判定侧同一实现）。东财对
    1998-2015 报告期普遍记的是**次年同期报告的公告日**（年报 70.6% 超截止日、封顶量中位 354 天），
    2016 年起仍有 6.7%~12.3% 的行偏移整一年；不封顶则带在早年晚约一年才可用、跨期比较不对等。
    下游 `available_at = max(所用各期公告日)`、`fiscal_years_before`、除权锚（`split_factor`／
    `exright_adjust` 的 `since`）全部读这一列，故只需在此一处改。原始记录日保留在 `notice_date_raw`。
    封顶行数计入 `roic_inputs.CAP_STATS`（`financials_rows`／`financials_capped`）。"""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for path in sorted(FIN_DIR.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                code = row["security_code"]
                if codes is not None and code not in codes:
                    continue
                notice = (row.get("notice_date") or "").strip()
                if not notice:
                    continue  # §12.4：无公告日的行不可用于历史建带
                roic_inputs.CAP_STATS["financials_rows"] += 1
                row["notice_date_raw"] = notice
                if notice_cap:
                    capped = statutory_available_at(row["report_date"], notice)
                    if capped != notice:
                        roic_inputs.CAP_STATS["financials_capped"] += 1
                        row["notice_date"] = capped
                out[code][row["report_date"]] = row
    from financials_corrections import apply_corrections, report as _corr_report
    _corr_report(*apply_corrections(out))
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


def annual_cash_roe(series: dict[str, dict], available_at: str, years: int) -> list[float]:
    """近 `years` 个已披露财年的**现金 ROE** ＝ 每股经营现金流 ÷ 每股净资产。

    这是「All Money Is Equal」口径（用户 2026-08-15）里 Owner Earnings 的落地方式：
    框架要的是 `NOPAT + D&A − 维持性资本开支 − ΔWC`，**本仓库的财务表没有这四项中的任何一项**
    （只有归母净利、营收、EPS、BPS、加权 ROE、毛利率、每股经营现金流）。
    可得的最接近替代是**经营现金流**——它天然含 D&A 与 ΔWC，缺的只有维持性资本开支。
    **故本口径是「税后经营现金 ÷ 净资产」而不是真正的 Owner Earnings**，
    它会系统性高估重资产公司（不扣维持性资本开支）、与轻资产公司的差距因此被压缩。
    这是数据边界不是建模选择，读结论时必须记住。

    用「每股现金流 ÷ 每股净资产」而不是绝对额：两者同为每股口径、同期同基，
    送转不影响比值，可直接与 `weightavg_roe` 并列进同一套归一化。
    """
    out = []
    for period in reversed(fiscal_years_before(series, available_at, years)):
        row = series[period]
        cfps, bps = _num(row.get("op_cashflow_ps")), _num(row.get("bps"))
        if cfps is None or bps is None or bps <= 0:
            continue
        out.append(cfps / bps)
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
              trend: str, lift: float = 1.0) -> tuple[float, str]:
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
        # **`--roe-lift λ` 把「去掉高位惩罚」由开关变成刻度**（用户 2026-08-11）：
        # `roe0 = 归一化值 + λ·(当期 − 归一化值)`，λ=0 即现行、λ=1 即完全采信当期。
        # **允许 λ>1 越过当期读数**——这一段是用来分辨两种解释的：若曲线过了 λ=1 还在涨，
        # 起作用的就不是「相信当期读数」而是「偏向 ROE 上行的那批公司」本身。
        # 只对 `当期 > 归一化值` 的一侧生效，低谷侧不动（低谷保护是这条规则的全部价值来源）。
        return normalized + lift * (roe_ttm_value - normalized), (
            "ttm(孰高)" if lift == 1.0 else f"lift{lift:g}(孰高)")
    if mode == "onesided_min" and roe_ttm_value < normalized:
        return roe_ttm_value, "ttm(孰低)"
    return normalized, "normalized"


def incremental_roe(series: dict[str, dict], actions: list[dict], available_at: str,
                    span: int = 4) -> float | None:
    """`incremental_roe_detail` 的取值部分（调用方不需要折算判定时用）。"""
    return incremental_roe_detail(series, actions, available_at, span)[0]


def incremental_roe_detail(series: dict[str, dict], actions: list[dict], available_at: str,
                           span: int = 4) -> tuple[float | None, str]:
    """增量股东回报 `ΔEPS / ΔBPS`——**新投进去的一块钱赚回多少**。返回 `(值, eps_old 折算判定)`。

    为什么必须单看它（外部评审 2026-08-08 提出，本仓库现有字段刚好够算）：
    `g = ROE × b` 隐含「新增资本能继续赚到与存量相同的 ROE」，这对多数非金融公司不成立。
    茅台过去 ROE 35%，不代表新投 100 亿还能产出 35 亿。真正决定增长的是**增量回报**，
    历史平均 ROE 只是它的一个有偏代理。

    两期的每股口径若跨过送转并不同基，故按公告日之间的累计送转比把旧期折算回来再相减。

    **OI-041（v4.32 修）：东财 `basic_eps` 在部分期已按后续送转折算过，而 `bps` 不折算**
    （160 个公司-年抽样与新浪「加权每股收益」相符 86.6%，不符者多为送转期；判例 002369·2010
    东财 0.37 = 新浪摊薄 0.7395 ÷ 2，对应 2011-05 的 10 转 10）。对已折算的期再除一次 `factor`
    会把 `eps_old` 压得过小、`ΔEPS` 与本列偏高。本地判据不依赖外部源：两期「归母净利 ÷ 每股收益」
    的**隐含股本之比** `jump`——`eps_old` 未折算时 `jump ≈ factor`，已折算时 `jump ≈ 1`（股本跳升
    已被折进 EPS），按对数距离取近者；`factor = 1`（期间无送转）时两种口径无区别、不判。
    判定结果记入 `incremental_roe_basis`（`raw`＝除 factor／`pre_adjusted`＝不除／`n/a`＝无送转或不可判），
    计数进 `IROE_BASIS_STATS`。
    """
    annuals = fiscal_years_before(series, available_at, span + 1)
    if len(annuals) < span + 1:
        return None, ""
    new_period, old_period = annuals[0], annuals[-1]
    new_row, old_row = series[new_period], series[old_period]
    factor = split_factor(actions, old_row["notice_date"], new_row["notice_date"])
    eps_new, eps_old = _num(new_row.get("basic_eps")), _num(old_row.get("basic_eps"))
    bps_new, bps_old = _num(new_row.get("bps")), _num(old_row.get("bps"))
    if None in (eps_new, eps_old, bps_new, bps_old):
        return None, ""
    eps_factor, basis = factor, "n/a"
    if factor > 1.0 + 1e-9:
        basis = "raw"
        np_new, np_old = _num(new_row.get("parent_netprofit")), _num(old_row.get("parent_netprofit"))
        if (np_new and np_old and eps_new and eps_old
                and np_new * eps_new > 0 and np_old * eps_old > 0):      # 净利与 EPS 同号才有隐含股本
            jump = (np_new / eps_new) / (np_old / eps_old)
            if jump > 0 and abs(math.log(jump) - math.log(factor)) > abs(math.log(jump)):
                eps_factor, basis = 1.0, "pre_adjusted"
    IROE_BASIS_STATS[basis] += 1
    delta_eps = eps_new - eps_old / eps_factor
    delta_bps = bps_new - bps_old / factor
    if delta_bps <= 0:
        return None, basis   # 净资产未增长时增量回报无定义（回购／分红超过留存）
    return delta_eps / delta_bps, basis


IROE_BASIS_STATS: dict[str, int] = defaultdict(int)   # OI-041：eps_old 折算判定计数（raw / pre_adjusted / n/a）


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
def exright_adjust(actions: list[dict], since: str, until: str,
                   values: tuple[float, ...]) -> tuple[list[float], float, float]:
    """`(since, until]` 内按交易所除权参考价公式逐事件调整带值：`v → (v − 现金红利) ÷ (1 + 送转比)`。

    v4.20（OI-052/OI-039，用户 2026-08-19 裁定「带跟随真实股价的除权调整」）：此前只做送转、
    不做现金分红——每个除息日股价下跳 `D` 而带不动，`P/V` 凭空下跳一次股息率，对高股息股
    产生系统性假买入倾向。现金与送转按事件顺序复合，与交易所除权参考价同一公式。

    锚取**公告日**（与 `split_factor` 同理，见其文档串）：报告披露时点通常已把已宣告分红
    计入应付股利（A 股股东大会多在 5-6 月、早于除权），故公告日之前的除息不再重复扣。
    已知残差：股东大会晚于报告期末且除息早于下一份报告公告的少数情形会漏扣一次 `D`，
    方向为带偏高、量级一个股息率、窗口至下一份报告披露即闭合。

    返回 (逐值调整后的列表, 累计送转因子, 累计现金——现金按各自后续送转折算到现价口径)。
    """
    factor, cash_cum = 1.0, 0.0
    vals = list(values)
    for action in actions:                      # load_actions 已按除权日排序
        ex_date = action.get("ex_dividend_date") or ""
        if since < ex_date <= until:
            cash = _num(action.get("cash_per_share")) or 0.0
            ratio = _num(action.get("share_ratio")) or 0.0
            vals = [(v - cash) / (1.0 + ratio) for v in vals]
            factor *= 1.0 + ratio
            cash_cum = (cash_cum + cash) / (1.0 + ratio)
    return vals, factor, cash_cum


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
    incremental_roe_basis: str = ""   # OI-041：raw / pre_adjusted / n/a（见 incremental_roe 文档串）
    # ---- All Money Is Equal 口径的字段（--value-model ame）----
    cash_roe0: float | None = None            # 正常化现金 ROE = 每股经营现金流 ÷ BPS
    owner_earnings0: float | None = None      # 每股 Owner Earnings（现金口径）
    v_zero_growth: float | None = None        # 框架 §1 的零增长锚 OE/r
    incremental_roe_used: float | None = None # 实际喂进引擎的 iROE（已封顶）
    ame_path: str | None = None               # growth ／ zero_growth
    # ---- ROIC/FCFF 真口径的字段（--value-model roic，OI-060 补数据后）----
    nopat_ps: float | None = None             # 每股 NOPAT = EBIT×(1−t) ÷ 股数
    roic0: float | None = None                # 正常化 ROIC（近 N 年中位）
    incremental_roic: float | None = None     # ΔNOPAT/ΔIC
    reinvestment_rate: float | None = None    # (capex − D&A + ΔWC)/NOPAT
    wacc: float | None = None
    cost_of_debt: float | None = None
    tax_rate: float | None = None
    net_debt_ps: float | None = None          # (有息负债 − 超额现金 + 少数股东权益)/股数
    ev_ps: float | None = None                # 企业价值/股（扣净负债前）
    owner_earnings_true_ps: float | None = None  # CFO − 维持性capex（≈D&A），每股
    roic_path: str | None = None              # growth ／ zero_growth ／ equity_fallback
    roic_nopat_mode: str = ""                 # median ／ onesided ／ cyclical_median
    roic_g_source: str = ""                   # capital ／ trailing ／ none
    mos: float | None = None
    max_buy_price: float | None = None
    value: float | None = None
    band_low: float | None = None
    band_high: float | None = None
    terminal_share: float | None = None
    implied_pe: float | None = None
    min_payout: float | None = None
    # ---- OI-074（v4.35）：输出列，不进任何交易判定 ----
    v_bear: float | None = None               # 悲观敏感度值（g0×0.5、折现率+1pp、终值回报−1pp、fade 7 年、g_T−0.5pp）
    v_bull: float | None = None               # 乐观敏感度值（g0×1.25 封顶、折现率−1pp、终值回报+1pp、fade 13 年、g_T+0.5pp）
    valuation_quality_score: int | None = None   # 0-100：历史长度／回报稳定性／终值占比／路径与守卫／两腿一致度各 20 分
    valuation_quality_notes: str = ""         # 各分项得分的短记号，便于逐行复核


def _cv(values: list[float]) -> float | None:
    """变异系数 σ/|均值|；观测 <3 或均值为 0 返回 None。"""
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return None
    mean = statistics.fmean(vals)
    if abs(mean) < 1e-12:
        return None
    return statistics.pstdev(vals) / abs(mean)


def quality_score(history_years: int, return_cv: float | None, terminal_share: float | None,
                  path_tag: str, leg_gap: float | None, legs: int) -> tuple[int, str]:
    """估值质量分（OI-074 ①，0-100）：五个分项各 20 分，分项定义见工作流 §6.5.3。

    * 历史长度：可用财年 ≥8 → 20；5~7 → 12；≤4 → 5
    * 回报稳定性（逐年 ROIC／ROE 的变异系数）：≤0.25 → 20；≤0.50 → 12；其余或不可算 → 5
    * 终值占比：≤0.60 → 20；≤0.75 → 12；其余 → 5
    * 路径与守卫：growth 且未触 peak 守卫 → 20；growth 触守卫或 zero_growth → 10；equity_fallback → 5
    * 两腿一致度（g 的资本腿 vs 增速腿；权益口径为 g_sustainable vs g_trailing）：两腿可算且差 ≤5pp → 20；≤10pp → 12；
      只有一腿 → 12；差 >10pp 或两腿皆无 → 5
    """
    s_hist = 20 if history_years >= 8 else 12 if history_years >= 5 else 5
    s_cv = 5 if return_cv is None else 20 if return_cv <= 0.25 else 12 if return_cv <= 0.50 else 5
    s_term = 5 if terminal_share is None else 20 if terminal_share <= 0.60 else 12 if terminal_share <= 0.75 else 5
    s_path = {"growth": 20, "growth_guarded": 10, "zero_growth": 10, "equity_fallback": 5}.get(path_tag, 5)
    if legs >= 2 and leg_gap is not None:
        s_leg = 20 if leg_gap <= 0.05 else 12 if leg_gap <= 0.10 else 5
    elif legs == 1:
        s_leg = 12
    else:
        s_leg = 5
    total = s_hist + s_cv + s_term + s_path + s_leg
    notes = f"hist{s_hist}/cv{s_cv}/term{s_term}/path{s_path}/legs{s_leg}"
    return total, notes


def sensitivity_values(eps0: float, roe0: float, g0: float, r: float, roe_t: float,
                       g_terminal: float, n: int, n1: int, g0_cap: float, spread: float,
                       less: float = 0.0) -> tuple[float | None, float | None]:
    """Bear/Bull 敏感度值（OI-074 ②）：同一引擎、五个参数同向扰动；任一护栏拒绝即该侧为 None。
    `less` 是要从企业价值里扣除的每股净负债（ROIC 口径），权益口径为 0。"""
    out = []
    for sign in (-1, +1):
        g_adj = g0 * (0.5 if sign < 0 else 1.25)
        g_adj = min(max(g_adj, 0.0), g0_cap)
        r_adj = r + (0.01 if sign < 0 else -0.01)
        gt_adj = g_terminal + (-0.005 if sign < 0 else 0.005)
        if gt_adj < 0:
            gt_adj = 0.0
        t_adj = roe_t + (-0.01 if sign < 0 else 0.01)
        if sign > 0:
            t_adj = min(t_adj, roe0)           # 终值回报不高于起点（竞争侵蚀方向不变）
        t_adj = max(t_adj, gt_adj + spread + 1e-6)
        if r_adj <= gt_adj + 1e-6 or eps0 <= 0 or roe0 <= 0:
            out.append(None)
            continue
        n_adj = max(3, n + (-3 if sign < 0 else 3))
        try:
            res = intrinsic_value(eps0, roe0, g_adj, r_adj, roe_terminal=t_adj,
                                  g_terminal=gt_adj, n=n_adj, n1=n1)
            value = res.intrinsic_value - less
            out.append(value if value > 0 else None)
        except ValuationError:
            out.append(None)
    return out[0], out[1]


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
        # `--terminal-excess X`（研究开关，缺省 None＝原行为）：终值超额回报改为显式给定，
        # `ROE_T = r + X`（roic 分支平移为 `ROIC_T = WACC + X`）。分档表里 L2 的 12% − 10% = 2pp
        # 正是现行生产的隐含超额；显式化是为了能在不动 r 的前提下单独扫终值假设（OI-070 ②）。
        if getattr(args, "terminal_excess", None) is not None:
            roe_t = r + args.terminal_excess

    # **逐票/分档参数覆盖**（`--moat-params CSV`，OI-070 护城河补偿实验）：只改终值超额与衰减年数
    # 两个「护城河持续多久、终值超额多大」的参数，**不改 r、不改增长、不改分子**——护城河只经由
    # 「超额回报持续多久」进入价值，绝不直接给好公司加倍数（评审五原则）。查不到的代码沿用全局。
    n_years, n1_years = args.n, args.n1
    override = MOAT_PARAMS.get(code)
    if override:
        if override.get("terminal_excess") is not None:
            roe_t = r + override["terminal_excess"]
        if override.get("fade_years") is not None:
            n_years = int(override["fade_years"])
        if override.get("n1") is not None:
            n1_years = int(override["n1"])
        MOAT_STATS["覆盖命中"] += 1
    elif MOAT_PARAMS:
        MOAT_STATS["无覆盖·沿用全局"] += 1

    iroe_value, iroe_basis = incremental_roe_detail(series, actions, available_at)
    band = Band(code, name, period, notice, available_at, "unavailable",
                eps_ttm=eps.value if eps else None, roe_ttm=roe.value if roe else None,
                roe_source=roe_source, bps=bps,
                g_trailing=trailing_cagr(series, period), r=r, r_mode=args.r_mode,
                rf=rf, erp=erp, beta=beta, g_terminal=g_terminal, roe_terminal=roe_t,
                mos=MOS_BY_TIER.get(tier),
                incremental_roe=iroe_value, incremental_roe_basis=iroe_basis)

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
            # **peak 守卫（--dcf-peak-guard K，实验，缺省关）**：当期 TTM ROE > K × 十年年度
            # ROE 中位时判「利润相对自身长史处于极端高位」，**跳过单边上抬**、退回归一化值。
            # 锚点诊断（§12.68）：λ=2.0 的单边抬在周期利润顶火上浇油——牧原 2020 读 0.51、
            # 方大特钢 2018 读 0.27，都把「顶部利润 × 上抬」当成了便宜。与 roic 口径的
            # `--roic-cycle-guard peak` 同一思想：要防的是把高位利润外推十年，不是「有来回」。
            peaked = False
            if getattr(args, "dcf_peak_guard", 0) and roe is not None:
                longs = [v for _p, v in annual_roe_series(series, available_at,
                                                          max(args.roe_years, 10))]
                peaked = (len(longs) >= 4 and roe.value > 0
                          and roe.value > args.dcf_peak_guard * statistics.median(longs))
            if peaked:
                band.roe0_mode = "normalized_peak_guard"
                ROIC_STATS["DCF peak 守卫·不上抬"] += 1
            else:
                roe0, band.roe0_mode = pick_roe0(args.roe_source, roe0,
                                                 roe.value if roe else None, band.roe_trend,
                                                 args.roe_lift)
        # **eps0 一律走清洁盈余 `E = ROE×B`**，与 normalized 臂同式——单边口径改的只有
        # 「roe0 取哪一侧」这一个自由度，若同时换 EPS 口径就分不清差异来自哪一处。
        eps0 = roe0 * bps
    # 外部 ROE 覆盖（实验用）：只换 roe0 这一个输入，EPS 仍走清洁盈余 E=ROE×B，
    # 折现率、终值、护栏全部沿用现行模型——这样回测差异只能归因到 ROE 预测本身。
    ext = EXTERNAL_ROE.get(code) if EXTERNAL_ROE else None
    if ext:
        i = bisect_right(ext, (available_at, float("inf"))) - 1
        if i >= 0:
            roe0 = ext[i][1]
            band.roe0_mode = "external"
            EXTERNAL_STATS["命中"] += 1
            if bps is not None and bps > 0:
                eps0 = roe0 * bps
        else:
            EXTERNAL_STATS["无当期预测"] += 1
    elif EXTERNAL_ROE:
        EXTERNAL_STATS["该股无预测"] += 1
    band.roe0, band.eps0 = roe0, eps0

    # ---------------- ROIC/FCFF 真口径（用户 2026-08-15，OI-060 补数据后）----------------
    # 这是「All Money Is Equal」框架 §2~§4 的**本来面目**：估的是企业整体产生的自由现金
    # （FCFF），折现率用 WACC，终值用 `EV/NOPAT = (1−g_T/ROIC_T)/(WACC−g_T)`，
    # 最后减净负债回到股权。§12.65 第一版只能拿经营现金流当 Owner Earnings（没扣资本开支），
    # 本版有了三大报表，`维持性资本开支`／`ΔWC`／`有息负债`／`超额现金` 全部实算。
    #
    # **引擎仍不用改**：把 `eps0→每股NOPAT`、`roe0→ROIC`、`r→WACC`、`roe_terminal→ROIC_T`
    # 喂进 `intrinsic_value`，它算出的 `payout×NOPAT` 恰是 `NOPAT×(1−再投资率)` ＝ FCFF，
    # 终值式恰是框架的 EV/NOPAT——**得到的是每股企业价值**，再减净负债即得每股股权价值。
    if getattr(args, "value_model", "dcf") == "roic":
        history = roic_inputs.years_before(ROIC_YEARS.get(code, {}), available_at, args.roe_years)
        latest = max(history, key=lambda y: y.period) if history else None
        # **整只股票没取到报表时退回权益口径而不是拒绝**：拒绝会把该股整条踢出宇宙，
        # 于是 A/B 同时变了「估值口径」与「候选池」两个变量，§12.30 明令不可（曾踩中）。
        # 退回并计数，读结论时按这个比例折价。
        if code not in ROIC_YEARS:
            band.roic_path = "equity_fallback"
            ROIC_STATS["无三大报表·退回权益口径"] += 1
        elif len(history) < args.min_roe_years:
            band.reason = f"三大报表年份仅 {len(history)} < 要求 {args.min_roe_years} 年"
            return band
        # **金融企业退回权益口径**（框架 §6）：银行/券商/保险的「有息负债」是经营性负债，
        # 投入资本与 FCFF 没有经济含义。不是降级处理，是框架本身的规定。
        elif latest.is_financial:
            band.roic_path = "equity_fallback"
            ROIC_STATS["金融企业退回权益口径"] += 1
        elif latest.parent_equity is None or not latest.parent_equity > 0 or bps is None or bps <= 0:
            band.status, band.reason = "rejected", "母公司权益或 BPS 不可用，股数无法反推"
            return band
        else:
            # **总额 → 每股一律走「除以母公司权益得比率，再乘当期 BPS」**，
            # 与本模块 `eps0 = roe0 × bps` 完全同式：比率是同一份年报内部的无量纲量，
            # 送转/增发都不影响它，乘上当期 BPS 后自动落在与价格序列相同的每股基准上。
            #
            # **不可以用「年报权益 ÷ 当期 BPS」反推股数**——年报权益一年内不变而 BPS 逐季变，
            # 分红除权当季 BPS 下跌会让隐含股数虚增。实测茅台每股 NOPAT 在年内
            # 39.42→43.57→40.11 来回摆动，摆幅全部来自六七月派息，不是经营变化。
            # **税率归一化**（OI-069 第 5 条，`--roic-tax-mode median`，研究开关，§12.100 实测滚5 −3.31 不采纳）：窗口内观测年税率的中位
            # 统一重算各年 NOPAT（副本，不碰共享的 ROIC_YEARS），比率锚、ROIC0、增量 ROIC、再投资率、
            # 利润增速腿与 WACC 的税盾全部同源；窗口内无观测年时保持逐年税率。缺省 latest = 现行逐位行为。
            tax_norm = None
            if getattr(args, "roic_tax_mode", "latest") == "median":
                tax_norm = roic_inputs.normalized_tax_rate(history)
                if tax_norm is not None:
                    history = roic_inputs.with_tax_rate(history, tax_norm)
                    latest = max(history, key=lambda y: y.period)
            roic0 = roic_inputs.normalized_roic(history)
            # **增量 ROIC 口径**（OI-069 第 2 条，`--roic-iroic-mode`，研究开关，缺省 endpoint＝生产）：
            # endpoint=窗口首尾；allpairs=窗口内任意两财年各算一次取中位（估计量噪声减半，但经
            # `max(资本腿, 增速腿)` 只升不降地抬 g0，23 起点滚5 −0.7pp，§12.100 不采纳）；allpairs_guarded=
            # 同上但只在首尾口径可算处给值（同样 −0.7pp）；multiwindow=3/5/7 年同终点多窗口取中位（回测中性、
            # 但不压噪声）；regression=逐年 ΔNOPAT~ΔIC 的 OLS β（水平坍塌、回测为负）。endpoint 以外各档回看
            # `--roic-iroic-years`（缺省 7）年，只影响资本腿的 iROIC，不动其它输入。
            iroic_mode = getattr(args, "roic_iroic_mode", "endpoint")
            if iroic_mode == "endpoint":
                iroic = roic_inputs.incremental_roic(history)
            else:
                iroic_hist = roic_inputs.years_before(ROIC_YEARS.get(code, {}), available_at,
                                                      max(args.roe_years, args.roic_iroic_years))
                if tax_norm is not None:
                    iroic_hist = roic_inputs.with_tax_rate(iroic_hist, tax_norm)
                iroic = {"multiwindow": roic_inputs.incremental_roic_multiwindow,
                         "allpairs": roic_inputs.incremental_roic_allpairs,
                         "allpairs_guarded": lambda h: roic_inputs.incremental_roic_allpairs_guarded(
                             h, base_years=args.roe_years),
                         "regression": roic_inputs.incremental_roic_regression}[iroic_mode](iroic_hist)
            rr = roic_inputs.reinvestment_rate(history)
            # OI-071 ②：债务成本口径（研究开关，缺省 historical＝生产）
            rd = None
            if getattr(args, "rd_mode", "historical") == "spread":
                observed = rates_as_of(args.rates, available_at)
                if observed is not None:
                    rd = roic_inputs.cost_of_debt_spread(history, observed[0])
                    ROIC_STATS["rd·国债+利差"] += 1
                else:
                    ROIC_STATS["rd·无当时利率观测退历史成本"] += 1
            if rd is None:
                rd = roic_inputs.cost_of_debt(history)
            tax = latest.tax_rate if latest.tax_rate is not None else roic_inputs.DEFAULT_TAX_RATE
            # OI-071 ①：WACC 股权权重（研究开关，缺省 book＝生产）。市值 = 可得日收盘 × 股本估计，
            # 股本 = 最新财年母公司权益 ÷ 该财年报告的 BPS，再乘该财年公告日→可得日的送转因子（同基）
            equity_weight = latest.total_equity or 0.0
            if getattr(args, "wacc_weights", "book") == "market":
                mcap = market_cap_at(code, series, actions, latest, available_at)
                if mcap:
                    equity_weight = mcap + (latest.minority_equity or 0.0)
                    ROIC_STATS["WACC·市值权重"] += 1
                else:
                    ROIC_STATS["WACC·市值不可得退账面"] += 1
            w = roic_inputs.wacc(r, rd, tax, equity_weight, latest.interest_debt)
            band.roic0, band.incremental_roic, band.reinvestment_rate = roic0, iroic, rr
            band.wacc, band.cost_of_debt, band.tax_rate = w, rd, tax
            if latest.nopat is None or latest.nopat <= 0:
                band.status, band.reason = "rejected", (
                    f"NOPAT={latest.nopat}: 息税前利润非正，按现金折现无意义，须走 §6.5.5.2 逐票建档")
                return band
            # 正常化 NOPAT：与 ROIC 同窗口取**比率**中位再乘 BPS，避免把单年高点/低谷外推十年
            ratios = [y.nopat / y.parent_equity
                      for y in sorted(history, key=lambda x: x.period)
                      if y.nopat is not None and y.parent_equity and y.parent_equity > 0]
            # OI-082 研究开关（用户 2026-08-23，海外先行后 A 股 A/B）：`--roic-nopat-anchor per_share`
            # 把各年比率一律相对**最新**母公司权益（× 当期 BPS 即「各年 NOPAT 按当前股数折每股」），
            # 回购缩水/留存增长造成的权益基数变化不再进入分子归一化；周期守卫则用「权益＋库存股」
            # （已回购未注销）作分母。缺省 ratio_bps＝现行，逐位不变。
            anchor_mode = getattr(args, "roic_nopat_anchor", "ratio_bps")
            if anchor_mode == "per_share":
                ratios = [y.nopat / latest.parent_equity
                          for y in sorted(history, key=lambda x: x.period)
                          if y.nopat is not None]
            if not ratios:
                band.status, band.reason = "rejected", "无可用的 NOPAT/母公司权益比率"
                return band
            # **周期股守卫**：判定为周期态时**不抬分子、不用利润增速**，只按中位＋资本口径
            # ——否则牧原/方大特钢一类会在利润顶被抬高分子、再被利润增速灌高 g，
            # 正好在最不该买的点读成便宜。两种探测器（--roic-cycle-guard）：
            # * efficiency：走势单调度 < 35%（镜像 DCF 臂）。**锚点实测它打错目标**——
            #   茅台 2018 的五年窗含 2014-15 的 V 型回撤（回到新高≠周期顶）被误杀增长腿，
            #   而牧原 2020 单边冲顶（单调度高）反而漏网（§12.67）。
            # * peak：**当前比率 > K × 十年长窗中位**。要防的从来不是「有来回」，
            #   是「把极端高位的利润外推十年」——直接量它。牧原 2020 ≈3× 长窗中位 → 拦下；
            #   茅台 2018 ≈1.1× → 放行。K 由 --roic-peak-k 给。
            if getattr(args, "roic_cycle_guard", "efficiency") == "peak":
                long_hist = roic_inputs.years_before(ROIC_YEARS.get(code, {}), available_at,
                                                     max(args.roe_years, 10))
                if tax_norm is not None:
                    long_hist = roic_inputs.with_tax_rate(long_hist, tax_norm)
                long_ratios = [y.nopat / (y.parent_equity + (y.treasury_shares if anchor_mode == "per_share" else 0.0))
                               for y in sorted(long_hist, key=lambda x: x.period)
                               if y.nopat is not None and y.parent_equity and y.parent_equity > 0]
                nopat_cyclical = (len(long_ratios) >= 4 and long_ratios[-1] > 0
                                  and long_ratios[-1] > args.roic_peak_k
                                  * statistics.median(long_ratios))
            else:
                nopat_cyclical = len(ratios) >= 3 and trend_efficiency(ratios) < 0.35
            ratio0 = statistics.median(ratios)
            band.roic_nopat_mode = "median"
            # **单边口径**（v2，镜像 §6.5.2.1 v2.90 的 `onesided_max λ`）：当期比率高于中位时
            # `ratio0 = 中位 + λ×(当期 − 中位)`——保留低谷保护（低于中位仍用中位），去掉高位惩罚。
            # 锚点诊断的直接动机：中际旭创 2018（壳→资产重组）当期比率远高于五年中位，
            # 纯中位给出每股 NOPAT 0.18、P/V=70 的荒唐读数；茅台一类快增长公司则被中位滞后约两年。
            nopat_src = getattr(args, "roic_nopat_source", "median")
            if nopat_src == "onesided_max" and not nopat_cyclical:
                current = ratios[-1]
                if current > ratio0:
                    ratio0 = ratio0 + args.roe_lift * (current - ratio0)
                    band.roic_nopat_mode = "onesided"
            elif nopat_src in ("conditional", "conditional3") and not nopat_cyclical:
                # 分型锚（§12.72）：增长态 → 采信当期（§12.36.2 已证「上行时采信当期」是正确方向、
                # 缩短窗口整体是反的）；非增长态（波动/下行）→ conditional 用五年中位、conditional3 用三年中位。
                # 周期守卫命中的仍然只吃中位——顶部外推的保护优先于分型。
                #
                # 增长态的判别（--roic-cond-detect）：
                # * strict：近三期严格单调上行（`a<b<c`）。干净但漏判——一次年度小回撤就出局，
                #   而多数真成长股都有这样的年份。
                # * soft：近三期里**两次上行**（含末期上行）且**当期高于窗口中位**。放宽的是
                #   「单调」这一条，没有放宽「当期确实更高」——后者才是采信当期的前提。
                rising = 0
                if len(ratios) >= 3:
                    rising = sum(1 for i in (-1, -2) if ratios[i] > ratios[i - 1])
                if getattr(args, "roic_cond_detect", "strict") == "soft":
                    is_growth = (len(ratios) >= 3 and rising >= 2
                                 and ratios[-1] > ratios[-2]
                                 and ratios[-1] > statistics.median(ratios))
                else:
                    is_growth = len(ratios) >= 3 and ratios[-1] > ratios[-2] > ratios[-3]
                # OI-073 ②（研究开关）：单调判据对幅度不敏感（0.10→0.101→0.102 与 0.10→0.15→0.22 同判），
                # 加最小幅度条件「当期 > X × 窗口中位」，不满足退回非增长态口径。
                min_ratio = getattr(args, "roic_growth_min_ratio", 0.0)
                if is_growth and min_ratio and ratios[-1] <= min_ratio * statistics.median(ratios):
                    is_growth = False
                    ROIC_STATS["增长态·幅度不足退非增长口径"] += 1
                if is_growth:
                    ratio0 = ratios[-1]
                    band.roic_nopat_mode = "ttm_growth"
                elif nopat_src == "conditional3" and len(ratios) >= 3:
                    ratio0 = statistics.median(ratios[-3:])
                    band.roic_nopat_mode = "median3"
            if nopat_cyclical:
                band.roic_nopat_mode = "cyclical_median"
                ROIC_STATS["NOPAT 周期守卫·按中位"] += 1
            nopat_ps = ratio0 * bps
            band.nopat_ps = nopat_ps
            if latest.cfo is not None:
                band.owner_earnings_true_ps = (
                    (latest.cfo - latest.dep_amort) / latest.parent_equity * bps)
            net_debt_ps = ((latest.interest_debt - latest.excess_cash
                            + latest.minority_equity) / latest.parent_equity * bps)
            band.net_debt_ps = net_debt_ps
            if nopat_ps <= 0:
                band.status, band.reason = "rejected", "正常化每股 NOPAT 非正"
                return band
            # 零增长锚（框架 §1）：EV = NOPAT/WACC。OI-073 ④（研究开关 `--roic-zero-anchor fcff`）：
            # 分子改 NOPAT×(1−窗口净再投资率)，净再投资率夹 [0, 0.5]（D&A 超过资本开支时不抬分子、资本最密集时最多砍半）。
            zero_numerator = nopat_ps
            if getattr(args, "roic_zero_anchor", "nopat") == "fcff" and rr is not None and rr > 0:
                zero_numerator = nopat_ps * (1.0 - min(rr, 0.5))
                ROIC_STATS["零增长锚·FCFF 分子"] += 1
            band.v_zero_growth = zero_numerator / w - net_debt_ps
            growth_mode = getattr(args, "roic_growth", "capital")
            # v1（capital）：ROIC、再投资率、增量 ROIC 任一不可用 → 整条退零增长永续。
            # v2（hybrid）：**只有 ROIC0 不可用才退零增长**——ΔIC ≤ 0（现金牛把投入资本
            # 越做越小）在 v1 里触发 iroic=None → 零增长，恰把「资本效率最好」误判成
            # 「没有增长」，茅台/五粮液 2018 年报因此在公认买点读成高估（锚点诊断 §12.67）。
            roic_ok = roic0 is not None and roic0 > g_terminal + args.min_terminal_spread
            usable = (roic_ok if growth_mode == "hybrid"
                      else roic_ok and rr is not None and iroic is not None)
            if not usable:
                value = band.v_zero_growth
                if value <= 0:
                    band.status, band.reason = "rejected", (
                        f"零增长股权价值 {value:.2f} ≤ 0：净负债超过零增长企业价值")
                    return band
                band.status, band.value, band.roic_path = "ok", value, "zero_growth"
                band.band_low, band.band_high = BAND_LOW_COEF * value, BAND_HIGH_COEF * value
                band.terminal_share, band.implied_pe = 1.0, value / nopat_ps
                band.g0 = 0.0
                if band.mos is not None:
                    band.max_buy_price = margin_of_safety(value, band.mos)
                # OI-074：零增长锚只对折现率敏感（±1pp）
                bear = zero_numerator / (w + 0.01) - net_debt_ps
                bull = zero_numerator / max(w - 0.01, g_terminal + args.min_terminal_spread) - net_debt_ps
                band.v_bear, band.v_bull = (bear if bear > 0 else None), (bull if bull > 0 else None)
                ordered_hist = sorted(history, key=lambda x: x.period)
                yearly = [roic_inputs.roic_of(y, prev) for prev, y in zip([None] + ordered_hist[:-1], ordered_hist)]
                band.valuation_quality_score, band.valuation_quality_notes = quality_score(
                    len(history), _cv([v for v in yearly if v is not None]), 1.0, "zero_growth", None, 0)
                return band
            # 框架 §4：**资本驱动的增长 g = 增量ROIC × 再投资率**。
            # 再投资率夹在 [0,1]：>1 表示靠外部融资扩张，那部分增长不属于现有股东。
            g_capital = None
            if rr is not None and iroic is not None and iroic > 0 and rr > 0:
                g_capital = min(iroic, args.iroe_cap) * min(rr, 1.0)
            if growth_mode == "hybrid":
                # **两条腿取大**：资本口径之外，允许「资本自由的增长」——提价/品牌/负营运
                # 资金驱动的利润增长在净再投资≈0 时照样发生（茅台 2018 RR=−16.6% 而利润
                # 五年翻倍）。利润增速本身是它的直接观测，乘 `--roic-trail-weight` 衰减。
                # **周期股守卫同样作用于这条腿**（利润顶的高增速不外推）。
                g_trail = None
                if not nopat_cyclical:
                    cagr = roic_inputs.trailing_nopat_cagr(history)
                    if cagr is not None and cagr > 0:
                        g_trail = cagr * args.roic_trail_weight
                candidates = [g for g in (g_capital, g_trail) if g is not None]
                g0_raw = max(candidates) if candidates else 0.0
                band.roic_g_source = ("trailing" if g_trail is not None
                                      and (g_capital is None or g_trail >= g_capital)
                                      else "capital" if g_capital is not None else "none")
                ROIC_STATS[f"g 来源·{band.roic_g_source}"] += 1
            else:
                g0_raw = g_capital if g_capital is not None else 0.0
                band.roic_g_source = "capital"
            g0 = max(min(g0_raw, args.g0_cap), args.g0_floor)
            band.g0 = g0
            # 终值 ROIC：与基准同规——基准 L2 是 `ROE_T = r + 2pp` 且 ≤ ROE0，
            # 这里平移成 `ROIC_T = WACC + 2pp` 且 ≤ ROIC0（竞争均衡下超额回报收敛）。
            roic_t = min(w + (roe_t - r), roic0)
            if roic_t <= g_terminal + args.min_terminal_spread:
                band.status, band.reason = "rejected", (
                    f"终值 ROIC={roic_t:.2%} 距 g_T={g_terminal:.2%} 不足 "
                    f"{args.min_terminal_spread:.1%}：可分配现金趋零、估值对分母任意敏感")
                return band
            band.roe_terminal = roic_t
            try:
                res = intrinsic_value(nopat_ps, roic0, g0, w, roe_terminal=roic_t,
                                      g_terminal=g_terminal, n=n_years, n1=n1_years)
            except ValuationError as exc:
                band.status, band.reason = "rejected", str(exc)
                return band
            band.ev_ps = res.intrinsic_value
            value = res.intrinsic_value - net_debt_ps
            if value <= 0:
                band.status, band.reason = "rejected", (
                    f"股权价值 {value:.2f} ≤ 0：净负债 {net_debt_ps:.2f} 超过企业价值 "
                    f"{res.intrinsic_value:.2f}，须走 §6.5.5.2 逐票建档")
                return band
            band.status, band.value, band.roic_path = "ok", value, "growth"
            band.band_low, band.band_high = BAND_LOW_COEF * value, BAND_HIGH_COEF * value
            # 终值占比按**企业价值**口径报（净负债不属于折现流）
            band.terminal_share, band.implied_pe = res.terminal_share, value / nopat_ps
            # OI-074：敏感度带与质量分（输出列，不进判定）
            band.v_bear, band.v_bull = sensitivity_values(
                nopat_ps, roic0, g0, w, roic_t, g_terminal, n_years, n1_years,
                args.g0_cap, args.min_terminal_spread, less=net_debt_ps)
            ordered_hist = sorted(history, key=lambda x: x.period)
            yearly = [roic_inputs.roic_of(y, prev) for prev, y in zip([None] + ordered_hist[:-1], ordered_hist)]
            legs = sum(1 for g in (g_capital, g_trail if growth_mode == "hybrid" else None) if g is not None)
            gap = (abs(g_capital - g_trail) if growth_mode == "hybrid" and g_capital is not None
                   and g_trail is not None else None)
            band.valuation_quality_score, band.valuation_quality_notes = quality_score(
                len(history), _cv([v for v in yearly if v is not None]), res.terminal_share,
                "growth_guarded" if nopat_cyclical else "growth", gap, legs)
            band.min_payout = res.min_payout
            if band.mos is not None:
                band.max_buy_price = margin_of_safety(value, band.mos)
            return band

    # ---------------- All Money Is Equal 口径（用户 2026-08-15）----------------
    # 框架的核心断言是：估值的底层不是 PE/PEG，而是「今天投的 1 元钱换来多少可分配现金」。
    # 落到本模块的代数上，**引擎不用改，改的是喂给它的三个输入**：
    #   分子   `eps0`  会计盈利 → **正常化经营现金流**（Owner Earnings 的可得替代）
    #   再投资 `roe0`  存量 ROE → **增量回报 iROE = ΔEPS/ΔBPS**
    #                  （框架 §4：决定增长价值的是「新投的 1 元能多赚多少」，不是存量资产赚了多少）
    #   增长   `g0`    存量ROE×b → **iROE × b**（框架 §2：g = ROIC × Reinvestment Rate）
    # 终值式 `(1−g_T/ROE_T)/(r−g_T)` 与显式期的 `1−g/ROE` 本来就是框架 §2/§6 的式子，原样沿用。
    #
    # **为什么不用 EV/ROIC/FCFF**：那需要 EBIT、税率、折旧摊销、资本开支、有息负债、现金、
    # 营运资金——**本仓库一项都没有**。框架 §6 本就规定金融企业走权益口径 `g=ROE×b`、
    # `PE=(1−g/ROE)/(r−g)`，本实现把该权益口径用于全部公司，差别是杠杆隐含而非显式。
    if getattr(args, "value_model", "dcf") == "ame":
        cash = annual_cash_roe(series, available_at, args.roe_years)
        if len(cash) < args.min_roe_years:
            band.reason = f"现金 ROE 仅 {len(cash)} 年 < 要求 {args.min_roe_years} 年"
            return band
        croe0 = statistics.median(cash)
        band.cash_roe0 = croe0
        if croe0 <= 0 or bps <= 0:
            band.status, band.reason = "rejected", (
                f"正常化现金 ROE={croe0:.2%} 非正：经营现金长期为负，按现金折现无意义，"
                f"须走 §6.5.5.2 逐票建档")
            return band
        oe0 = croe0 * bps
        iroe = incremental_roe(series, actions, available_at)
        band.owner_earnings0 = oe0
        # 零增长锚（框架 §1）：`V0 = OwnerEarnings / r`。它是整个体系的零点，
        # 也是 §5「先算 g=0 的价值，再看当前价格要求多少增长」的比较基准，故一律记录。
        band.v_zero_growth = oe0 / r
        # `iROE` 噪声极大（全池 P5 −19.8%、P95 52.5%、17% 为负，见 §12.9 的实测）。
        # **不可用时不猜增长，直接退回零增长永续**——这正是框架 §5 的稳健主张：
        # 与其预测 g，不如先给出 g=0 的价值。落到这里就是 `V = OE/r`。
        if iroe is None or iroe <= g_terminal + args.min_terminal_spread:
            band.status = "ok"
            band.value = band.v_zero_growth
            band.band_low = BAND_LOW_COEF * band.value
            band.band_high = BAND_HIGH_COEF * band.value
            band.terminal_share = 1.0
            band.implied_pe = band.value / oe0
            band.g0, band.roe_terminal, band.ame_path = 0.0, None, "zero_growth"
            if band.mos is not None:
                band.max_buy_price = margin_of_safety(band.value, band.mos)
            return band
        iroe = min(iroe, args.iroe_cap)
        band.incremental_roe_used = iroe
        payout, _yrs = payout_ratio(series, actions, available_at)
        band.payout = payout
        if payout is None:
            band.reason = "派息率不可算：近三年无正 EPS 财年"
            return band
        g0 = max(min(iroe * (1 - payout), args.g0_cap), args.g0_floor)
        band.g0 = g0
        band.g_sustainable = roe0 * (1 - payout)      # 记录存量口径以便与增量口径对照
        roe_t_ame = min(roe_t, iroe)
        if roe_t_ame <= g_terminal + args.min_terminal_spread:
            band.status, band.reason = "rejected", (
                f"终值回报 {roe_t_ame:.2%} 距 g_T={g_terminal:.2%} 不足 "
                f"{args.min_terminal_spread:.1%}：可分配现金趋零、估值对分母任意敏感")
            return band
        band.roe_terminal = roe_t_ame
        try:
            res = intrinsic_value(oe0, iroe, g0, r, roe_terminal=roe_t_ame,
                                  g_terminal=g_terminal, n=n_years, n1=n1_years)
        except ValuationError as exc:
            band.status, band.reason = "rejected", str(exc)
            return band
        band.status, band.value = "ok", res.intrinsic_value
        band.band_low = BAND_LOW_COEF * res.intrinsic_value
        band.band_high = BAND_HIGH_COEF * res.intrinsic_value
        band.terminal_share, band.implied_pe = res.terminal_share, res.implied_pe
        band.min_payout, band.ame_path = res.min_payout, "growth"
        if band.mos is not None:
            band.max_buy_price = margin_of_safety(res.intrinsic_value, band.mos)
        return band

    # **终值 ROE 不得高于起始 ROE**：本模型的 fade 是「竞争侵蚀超额回报」的衰减机制，
    # 不是「困境反转」的复苏机制。把 `ROE_T = r + 超额` 硬套到低谷公司上，等于凭空假设它
    # 回升到行业均值——实测中国船舶 2019 各期 ROE0 仅 **0.24%**、终值被设为约 10%，
    # 模型据此算出隐含 PE **391**，价值全部来自那个没有证据的复苏假设。
    # 压到 `min(ROE_T, ROE0)` 后，这类公司多半会被下面的 `ROE_T > g_T` 护栏拦掉，
    # **正确地转去 §6.5.5.2 逐票建档**——低谷反转本就不该由批量模型定价。
    roe_t = min(roe_t, roe0) if roe0 > 0 else roe_t

    # **公司特定的终值 ROE**（`--roe-terminal-ratio K`，2026-08-15 用户指令）：`ROE_T = K × roe0`，
    # 取代按分档定死的常数。动机见 OI-050——`--uniform-tier L2` 下 `ROE_T` 对每家公司都是 12%，
    # 于是终值 PE 恒为 11.04，而终值占内在价值 74%~100%，整套估值在排序上退化成 PE 筛子。
    #
    # **必须设下限，否则这个实验测的就不是同一件事**：低 ROE 公司在 K=1/3 下 `ROE_T` 会掉到
    # `g_T + 2pp` 之下而被下面的护栏整条拒绝，等于「改估值」顺带「把一批公司剔出面板」，
    # 两个变量混在一起。故这里夹在 `[g_T + min_terminal_spread, roe0]` 内并计数落地情况。
    if getattr(args, "roe_terminal_ratio", None) and roe0 > 0:
        floor = g_terminal + args.min_terminal_spread
        want = args.roe_terminal_ratio * roe0
        roe_t = min(max(want, floor), roe0)
        EXTERNAL_STATS["ROE_T 触下限" if want < floor else "ROE_T 按比例"] += 1
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
                                 g_terminal=g_terminal, n=n_years, n1=n1_years)
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
    # OI-074：敏感度带与质量分（输出列，不进判定）
    band.v_bear, band.v_bull = sensitivity_values(
        eps0, roe0, g0, r, roe_t, g_terminal, n_years, n1_years, args.g0_cap, args.min_terminal_spread)
    roe_hist = [v for _p, v in annual_roe_series(series, available_at, max(args.roe_years, 10))]
    legs_e = sum(1 for g in (band.g_sustainable, band.g_trailing) if g is not None)
    gap_e = (abs(band.g_sustainable - band.g_trailing)
             if band.g_sustainable is not None and band.g_trailing is not None else None)
    band.valuation_quality_score, band.valuation_quality_notes = quality_score(
        len(roe_hist), _cv(roe_hist), result.terminal_share, "equity_fallback", gap_e, legs_e)
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


# 逐日状态里「某一天用哪条带」的生效口径（`--state-effective`，v4.28 用户裁定）：
#   prev_trading_day（缺省）：带自 **可得日之前的最后一个交易日** 起生效——A 股定期报告在非交易时段披露、
#       官方公告日戳次日（8.31 的公告 8.30 晚上已有），生产扫描在戳日凌晨以 as-of=戳日 吸收并用 8.30 收盘出信号、
#       8.31 执行（§6.7 v4.27）；回测须与之同构：8.30 的状态行即用新带。
#   notice：带自公告日当天起生效（v4.27 及之前的旧口径，信号比生产晚一个交易日）。只用于复现旧产物。
STATE_EFFECTIVE = "prev_trading_day"


def effective_keys(usable: list[Band], prices: list[tuple[str, float]]) -> list[str]:
    """每条带在逐日状态里的生效日（升序，与 `usable` 同序）。

    `prev_trading_day`：该股价格序列里**严格早于** `available_at` 的最后一个交易日；可得日之前没有
    交易日（上市首段）则退回 `available_at` 本身。同一间隙（如周六、周日、周一三个公告日）映射到同一个
    周五——`applicable_bands` 已按报告期新者在后排序，`bisect_right` 取到的正是最新那条。
    """
    if STATE_EFFECTIVE != "prev_trading_day":
        return [b.available_at for b in usable]
    # 「前一交易日」按**市场日历**（上证指数行情日）取，不按个股自身日期：个股停牌时带仍应在
    # 复牌首日起用（市场前一交易日 ≤ 复牌日，bisect 自然落到复牌首行），不该挂到停牌前最后一行。
    days = MARKET_DAYS or [d for d, _ in prices]
    keys = []
    for b in usable:
        j = bisect_left(days, b.available_at)            # 首个 ≥ available_at 的日历日下标
        prev = days[j - 1] if j >= 1 else None
        # 护栏（§12.4 前视）：日历里**没有** ≥ 可得日的交易日，说明行情库在该公告之前就断了
        # （陈旧），此时只有「间隔 ≤ 4 个日历日」（周末/短假）才认前一交易日，否则退回可得日当天
        # 生效（对陈旧序列即等于不出现）；日历覆盖到可得日之后的历史数据不受此限（长假亦可）。
        covered = j < len(days)
        if prev is not None and (covered or (_date(b.available_at) - _date(prev)).days <= 4):
            keys.append(prev)
        else:
            keys.append(b.available_at)
    return keys


MARKET_DAYS: list[str] = []          # 上证指数行情日，`main()` 装载；空则退回个股自身日期
MARKET_CALENDAR = OHLCV_DIR / "INDEX_000001.csv"


def load_market_days() -> list[str]:
    if not MARKET_CALENDAR.exists():
        return []
    with MARKET_CALENDAR.open(newline="", encoding="utf-8") as handle:
        return sorted(r["date"] for r in csv.DictReader(handle) if r.get("date"))


def _date(text: str):
    from datetime import date
    return date.fromisoformat(text)


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
    # 生效日按 `--state-effective`（缺省「可得日前一交易日」，与生产扫描的当晚吸收同构）；
    # `band_available_at` 列仍记录原始可得日，故该列可能晚于 `date` 一个交易日——这是口径的一部分。
    keys = effective_keys(usable, prices)
    out = []
    for date, close in prices:
        index = bisect_right(keys, date) - 1
        if index < 0:
            continue
        band = usable[index]
        # 坑 4：带按**公告时**的股本口径，价格是不复权的 → 按公告后的除权事件折算带。
        # v4.20 起现金分红与送转同折（OI-052/OI-039），公式与交易所除权参考价一致。
        (low, value, high), factor, cash_cum = exright_adjust(
            actions, band.notice_date, date, (band.band_low, band.value, band.band_high))
        if value <= 0:
            EXRIGHT_NEGATIVE.append(f"{code}@{date}")
            continue
        out.append({
            "security_code": code,
            "date": date,
            "close": f"{close:.4f}",
            "band_report_date": band.report_date,
            "band_available_at": band.available_at,
            "split_factor": f"{factor:.6f}",
            "cash_adjustment": f"{cash_cum:.4f}",
            "intrinsic_value": f"{value:.4f}",
            "band_low": f"{low:.4f}",
            "band_high": f"{high:.4f}",
            "valuation_ratio": f"{close / value:.4f}",
            "upside_to_low": f"{low / close - 1:.4f}",
            "valuation_label": valuation_label(close, value),
        })
    return out


# 现金调整把带穿到非正值的 (代码, 日) —— 不该发生，发生即须人工看（§13 第 3 条：不许静默）。
EXRIGHT_NEGATIVE: list[str] = []

# OI-074 ③：每只的 (代码, 最新 ok 带路径, NOPAT 口径, 市值代理)；结尾按路径打印只数、市值占比与行业集中度，
# 防某类公司因数据问题系统性换模型而不可见。行业取 `a_share_company_analysis_index.csv` 的门类（去掉字母前缀）。
PATH_STATS: list[tuple[str, str, str | None, float | None]] = []
INDUSTRY_FILE = ROOT / "data/processed/a_share_company_analysis_index.csv"


def load_industries() -> dict[str, str]:
    if not INDUSTRY_FILE.exists():
        return {}
    out = {}
    with INDUSTRY_FILE.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            ind = (r.get("industry") or "").strip()
            if ind and ind[0].isascii() and ind[0].isalpha():
                ind = ind[1:].strip()            # 「C 制造业」与「制造业」归一
            out[(r.get("security_code") or "").zfill(6)] = ind or "未知"
    return out


def print_path_distribution() -> None:
    """OI-074 ③：按最新 ok 带路径打印只数、市值占比（有市值代理的部分）与前三行业。"""
    if not PATH_STATS:
        return
    from collections import Counter
    industries = load_industries()
    by_path: dict[str, list] = defaultdict(list)
    for code, path, mode, mcap in PATH_STATS:
        key = f"{path}（peak 守卫）" if mode == "cyclical_median" and path == "growth" else path
        by_path[key].append((code, mcap, industries.get(code, "未知")))
    total_n = len(PATH_STATS)
    total_mcap = sum(m for _c, _p, _m, m in PATH_STATS if m) or 0.0
    print(f"路径分布（每只最新 ok 带，{total_n:,} 只；市值占比按有市值代理的 {sum(1 for x in PATH_STATS if x[3]):,} 只算）：")
    for key, items in sorted(by_path.items(), key=lambda kv: -len(kv[1])):
        mcap = sum(m for _c, m, _i in items if m)
        top = Counter(i for _c, _m, i in items).most_common(3)
        print(f"  {key}: {len(items):,} 只（{len(items) / total_n:.1%}）｜市值占比 {mcap / total_mcap if total_mcap else 0:.1%}"
              f"｜行业前三 " + "、".join(f"{name} {n}" for name, n in top))


# OI-071 ①：`--wacc-weights market` 要在建带时读该股的不复权收盘；主循环在建带前把本只的价格序列放这里。
CURRENT_PRICES: dict[str, list[tuple[str, float]]] = {}


def market_cap_at(code: str, series: dict[str, dict], actions: list[dict],
                  latest, available_at: str) -> float | None:
    """可得日市值（元）：可得日前最后一个收盘 × 股本估计；股本 = 最新财年母公司权益 ÷ 该财年 BPS × 该财年公告日→可得日送转因子。"""
    prices = CURRENT_PRICES.get(code)
    row = series.get(latest.period)
    if not prices or not row or not latest.parent_equity or latest.parent_equity <= 0:
        return None
    bps_year = _num(row.get("bps"))
    if not bps_year or bps_year <= 0:
        return None
    shares = latest.parent_equity / bps_year * split_factor(actions, row["notice_date"], available_at)
    i = bisect_right(prices, (available_at, float("inf"))) - 1
    if i < 0:
        return None
    return prices[i][1] * shares


# ------------------------------------------------------------------ 输出
BAND_FIELDS = ["security_code", "security_name", "quality_tier", "report_date", "notice_date",
               "available_at", "status", "reason", "eps_ttm", "roe_ttm", "roe_source", "bps",
               "eps0", "roe0", "roe_anchor", "roe_trend", "roe0_normalized", "roe0_mode",
               "growth_confirmed", "roe_window", "roe_efficiency",
               "incremental_roe", "incremental_roe_basis", "cash_roe0", "owner_earnings0", "v_zero_growth",
               "incremental_roe_used", "ame_path",
               "nopat_ps", "roic0", "incremental_roic", "reinvestment_rate", "wacc",
               "cost_of_debt", "tax_rate", "net_debt_ps", "ev_ps",
               "owner_earnings_true_ps", "roic_path", "roic_nopat_mode", "roic_g_source",
               "payout", "g_trailing", "g_sustainable", "g0", "g0_capped",
               "r_mode", "rf", "erp", "beta", "r", "g_terminal", "roe_terminal",
               "intrinsic_value", "band_low", "band_high", "mos", "max_buy_price",
               "implied_pe", "pe_on_ttm_eps", "terminal_share", "min_payout",
               "v_bear", "v_bull", "valuation_quality_score", "valuation_quality_notes"]


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
        "incremental_roe_basis": band.incremental_roe_basis or "",
        "cash_roe0": fmt(band.cash_roe0), "owner_earnings0": fmt(band.owner_earnings0),
        "v_zero_growth": fmt(band.v_zero_growth),
        "incremental_roe_used": fmt(band.incremental_roe_used),
        "ame_path": band.ame_path or "",
        "nopat_ps": fmt(band.nopat_ps), "roic0": fmt(band.roic0, 4),
        "incremental_roic": fmt(band.incremental_roic, 4),
        "reinvestment_rate": fmt(band.reinvestment_rate, 4),
        "wacc": fmt(band.wacc, 4), "cost_of_debt": fmt(band.cost_of_debt, 4),
        "tax_rate": fmt(band.tax_rate, 4), "net_debt_ps": fmt(band.net_debt_ps),
        "ev_ps": fmt(band.ev_ps),
        "owner_earnings_true_ps": fmt(band.owner_earnings_true_ps),
        "roic_path": band.roic_path or "",
        "roic_nopat_mode": band.roic_nopat_mode, "roic_g_source": band.roic_g_source,
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
        "v_bear": fmt(band.v_bear), "v_bull": fmt(band.v_bull),
        "valuation_quality_score": "" if band.valuation_quality_score is None else str(band.valuation_quality_score),
        "valuation_quality_notes": band.valuation_quality_notes or "",
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
        if IROE_BASIS_STATS:
            print("增量 ROE 的 eps_old 折算判定（OI-041）：" + "｜".join(
                f"{k} {v:,}" for k, v in sorted(IROE_BASIS_STATS.items())))
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
    # 与「压根没查」在报告上长得一样（§13 第 3 条）。
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
                        help="tier=§6.5.2.1 分档中位（旧）；market=R_f+βERP 逐期取值（需利率序列）")
    parser.add_argument("--roe-lift", type=float, default=1.0, metavar="LAMBDA",
                        help="onesided_max 专用：roe0 = 归一化值 + λ·(当期 − 归一化值)，只对当期偏高的一侧生效。"
                             "λ=0 退回归一化、λ=1 即完全采信当期、λ>1 为外推（见 pick_roe0）")
    parser.add_argument("--roe-external", type=Path, metavar="CSV",
                        help="用外部预测的 ROE 覆盖 roe0（列：security_code,available_at,roe0）。"
                             "取 available_at ≤ 本期可得日的最后一条；查不到的期次维持原口径并计数。"
                             "供实验用（scripts/experimental），不参与任何生产流程")
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
    parser.add_argument("--roe-terminal-ratio", type=float, metavar="K",
                        help="终值 ROE 改按公司自身定：ROE_T = K × roe0，夹在 "
                             "[g_T + min-terminal-spread, roe0] 内。缺省不启用（按分档常数）")
    parser.add_argument("--terminal-excess", type=float, metavar="X",
                        help="终值超额回报显式给定：ROE_T = r + X（roic 口径为 ROIC_T = WACC + X，仍 ≤ ROIC0）。"
                             "缺省不启用＝按分档表（uniform L2 隐含 2pp）。研究开关（OI-070 ②）")
    parser.add_argument("--moat-params", type=Path, metavar="CSV",
                        help="逐票/分档终值参数覆盖（列：security_code,fade_years,terminal_excess,n1，"
                             "空格即沿用全局）。只改「超额回报持续多久、终值超额多大」，不改 r/增长/分子。"
                             "缺省不启用，既往产出逐位可复现。研究开关（OI-070 ①②）")
    parser.add_argument("--g0-cap", type=float, default=0.25, help="g0 上限，缺省 25%%")
    parser.add_argument("--g0-floor", type=float, default=0.0)
    parser.add_argument("--g0-shrink", type=float, default=1.0,
                        help="g0 乘数，1.0=原行为。用于检验「该资本化多少增长」的响应曲线")
    parser.add_argument("--g-terminal", type=float, default=DEFAULT_G_TERMINAL)
    parser.add_argument("--n", type=int, default=10, help="fade 年数（非高增长年数，见文件头）")
    parser.add_argument("--n1", type=int, default=0,
                        help="高速期年数：前 n1 年 ROE 与 g 维持起始值不衰减，其后再 fade n 年。"
                             "缺省 0 = 原行为（g 自第 1 年即衰减）")
    parser.add_argument("--value-model", choices=("dcf", "ame", "roic"), default="dcf",
                        help="dcf=现行口径（会计盈利 ＋ 存量 ROE）；"
                             "ame=All Money Is Equal 的现金流代理版（经营现金流 ＋ iROE，"
                             "**没扣资本开支**，见 §12.65）；"
                             "roic=同框架的真口径（NOPAT/投入资本/FCFF/WACC，需三大报表，见 §12.66）")
    parser.add_argument("--statements-dir", type=Path, default=roic_inputs.STMT_DIR,
                        help="--value-model roic 的三大报表目录，缺省 data/raw/financials_statements/")
    parser.add_argument("--roic-ic-floor", type=float, default=0.0, metavar="K",
                        help="投入资本下限 = K×总权益，挡住现金厚公司 IC 趋零导致的 ROIC 发散"
                             "（格力 2018 实测 793.7%%）。缺省 0 = v1 行为")
    parser.add_argument("--roic-nopat-anchor", choices=("ratio_bps", "per_share"), default="ratio_bps",
                        help="OI-082 研究开关：ratio_bps=各年 NOPAT/当年权益 的比率×当期 BPS（现行）；"
                             "per_share=各年 NOPAT/最新权益×BPS（＝按当前股数折每股），周期守卫分母加库存股")
    parser.add_argument("--roic-nopat-source",
                        choices=("median", "onesided_max", "conditional", "conditional3"),
                        default="median",
                        help="正常化 NOPAT 比率的口径：median=五年中位（v1）；onesided_max=当期高于"
                             "中位时按 --roe-lift 的 λ 单边上抬（镜像 §6.5.2.1 v2.90），周期股除外；"
                             "conditional=分型锚（§12.72，用户 2026-08-17 思路）——近三年比率单调上行"
                             "（增长态）且未触发周期守卫时**采信当期**，否则五年中位；"
                             "conditional3=同上但非增长态用**三年**中位。两档都建议配 --roic-cycle-guard peak")
    parser.add_argument("--roic-cond-detect", choices=("strict", "soft"), default="strict",
                        help="conditional/conditional3 的增长态判别：strict=近三期严格单调上行；"
                             "soft=近三期两次上行且当期高于窗口中位（放宽单调，不放宽「当期更高」）")
    parser.add_argument("--roic-growth", choices=("capital", "hybrid"), default="capital",
                        help="g 的口径：capital=增量ROIC×再投资率（v1，资本驱动）；hybrid=与利润"
                             "增速两条腿取大（资本自由的增长不再被判 0），周期股只走资本腿")
    parser.add_argument("--roic-trail-weight", type=float, default=1.0, metavar="W",
                        help="hybrid 中利润增速那条腿的权重（g_trail = W × NOPAT 五年CAGR），缺省 1.0")
    parser.add_argument("--roic-cycle-guard", choices=("efficiency", "peak"), default="efficiency",
                        help="周期守卫的探测器：efficiency=走势单调度<35%%（镜像 DCF 臂）；"
                             "peak=当前比率>K×十年中位（防的是把高位利润外推，锚点实测更准）")
    parser.add_argument("--roic-peak-k", type=float, default=1.6, metavar="K",
                        help="peak 守卫的倍数阈值，缺省 1.6")
    parser.add_argument("--dcf-peak-guard", type=float, default=0.0, metavar="K",
                        help="DCF 臂的 peak 守卫：当期 TTM ROE > K×十年年度 ROE 中位时不做单边上抬"
                             "（周期利润顶不外推）。缺省 0 = 关（现行生产行为）")
    parser.add_argument("--iroe-cap", type=float, default=0.40, metavar="X",
                        help="iROE 的上限，防止个别极端读数把估值推到发散；缺省 40%%")
    parser.add_argument("--roic-iroic-mode",
                        choices=("endpoint", "multiwindow", "allpairs", "allpairs_guarded", "regression"),
                        default="endpoint",
                        help="增量 ROIC 的估计口径（OI-069 第 2 条，研究开关）：endpoint=窗口首尾 ΔNOPAT/ΔIC（生产）；"
                             "allpairs=窗口内任意两财年各算一次、取中位（噪声减半但经 max() 抬高 g0，滚5 −0.74，§12.100 不采纳）；"
                             "allpairs_guarded=同上但只在首尾口径可算处给值（滚5 −0.72，不采纳）；"
                             "multiwindow=3/5/7 年同终点多窗口取中位（回测中性但不压噪声）；regression=逐年 ΔNOPAT~ΔIC 的 OLS "
                             "斜率（水平坍塌、回测为负）。endpoint 以外各档回看 --roic-iroic-years 年")
    parser.add_argument("--roic-iroic-years", type=int, default=7,
                        help="multiwindow/regression 口径的回看年数，缺省 7（不少于 --roe-years）")
    parser.add_argument("--roic-tax-mode", choices=("latest", "median"), default="latest",
                        help="NOPAT 与 WACC 税盾用的税率（OI-069 第 5 条，研究开关）：latest=各年自己的单期税率、WACC 用"
                             "最新年（生产）；median=窗口内观测年税率的中位统一重算各年 NOPAT（等于把增速腿改成 EBIT 增速，"
                             "§12.100 实测滚5 −3.31／5/23，不采纳）")
    parser.add_argument("--state-effective", choices=("prev_trading_day", "notice"),
                        default="prev_trading_day",
                        help="逐日状态里带的生效日：prev_trading_day=可得日前一交易日（缺省，v4.28，与生产"
                             "扫描当晚吸收同构）；notice=公告日当天（v4.27 前旧口径，只用于复现旧产物）")
    parser.add_argument("--wacc-weights", choices=("book", "market"), default="book",
                        help="WACC 权重（OI-071 ①，研究开关）：book=账面（缺省，生产）；market=可得日市值×(1+可得日前送转)"
                             "作股权权重（按带期报告的 BPS 反推股本），市值不可得退账面")
    parser.add_argument("--rd-mode", choices=("historical", "spread"), default="historical",
                        help="债务成本（OI-071 ②，研究开关）：historical=利息/平均有息负债夹 2~12%%（缺省，生产）；"
                             "spread=可得日十年国债 + 按利息覆盖倍数查表的信用利差（无当时利率观测退 historical）")
    parser.add_argument("--roic-growth-min-ratio", type=float, default=0.0, metavar="X",
                        help="增长态最小幅度条件（OI-073 ②，研究开关）：增长态还须 当期比率 > X × 窗口中位（如 1.10）；0=关（缺省）")
    parser.add_argument("--roic-zero-anchor", choices=("nopat", "fcff"), default="nopat",
                        help="零增长锚分子（OI-073 ④，研究开关）：nopat=NOPAT/WACC（缺省，隐含 D&A=维持性资本开支）；"
                             "fcff=NOPAT×(1−窗口净再投资率，夹 [0,0.5])/WACC")
    parser.add_argument("--notice-cap", choices=("statutory", "off"), default="statutory",
                        help="公告日封顶（OI-042 建带侧）：statutory=逐季财务与三大报表的公告日在装载时改为"
                             " min(记录公告日, 法定截止日)（缺省）；off=按东财记录日原样（只用于复现旧产物）")
    parser.add_argument("--out-bands", type=Path)
    parser.add_argument("--out-daily", type=Path)
    args = parser.parse_args()
    global STATE_EFFECTIVE
    STATE_EFFECTIVE = args.state_effective
    if STATE_EFFECTIVE == "prev_trading_day":
        MARKET_DAYS[:] = load_market_days()
        if MARKET_DAYS:
            print(f"市场日历：{MARKET_CALENDAR.name} {len(MARKET_DAYS):,} 个交易日（{MARKET_DAYS[0]}~{MARKET_DAYS[-1]}）"
                  f"——逐日状态生效日取可得日前一市场交易日")
        else:
            print(f"⚠ 未找到 {MARKET_CALENDAR.name}，前一交易日退回按个股自身日期")

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
    if args.roe_external:
        with args.roe_external.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    v = float(r["roe0"])
                except (KeyError, TypeError, ValueError):
                    continue
                if v == v:
                    EXTERNAL_ROE.setdefault(r["security_code"].zfill(6), []).append(
                        (r["available_at"], v))
        for seq in EXTERNAL_ROE.values():
            seq.sort()
        print(f"外部 ROE 预测：{len(EXTERNAL_ROE)} 只、"
              f"{sum(len(v) for v in EXTERNAL_ROE.values()):,} 条 ← {args.roe_external}")
    if args.moat_params:
        with args.moat_params.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                code = (r.get("security_code") or "").strip().zfill(6)
                if not code or code == "000000":
                    continue
                entry: dict[str, float | int | None] = {}
                for key, cast in (("fade_years", int), ("terminal_excess", float), ("n1", int)):
                    raw = (r.get(key) or "").strip()
                    entry[key] = cast(float(raw)) if raw else None
                MOAT_PARAMS[code] = entry
        print(f"逐票终值参数覆盖：{len(MOAT_PARAMS)} 只 ← {args.moat_params}"
              f"（fade_years/terminal_excess/n1 任一列给值即覆盖，空即沿用全局）")
    if getattr(args, "terminal_excess", None) is not None:
        print(f"**全局终值超额显式给定 {args.terminal_excess:+.1%}**（ROE_T/ROIC_T = r/WACC + 超额，≤ 起始回报）")

    tiers = load_tiers()
    financials = load_financials(set(codes), notice_cap=(args.notice_cap == "statutory"))
    actions = load_actions()
    if args.value_model == "roic":
        # `--roe-terminal-ratio` 改的是 `roe_t`，而 roic 分支在它生效**之前**就返回了，
        # 给了会静默无效——静默无效比报错危险得多（会以为测了其实没测）。
        if getattr(args, "roe_terminal_ratio", None):
            print("**--roe-terminal-ratio 对 roic 口径无效**（终值用 ROIC_T = WACC + 超额），"
                  "请去掉后重跑，避免读成「测过了」")
            return 1
        ROIC_YEARS.update(roic_inputs.load_statements(set(codes), args.statements_dir,
                                                      ic_floor=args.roic_ic_floor,
                                                      notice_cap=(args.notice_cap == "statutory")))
        if not ROIC_YEARS:
            print(f"**{args.statements_dir} 无三大报表**，roic 口径无法建带。"
                  f"先跑 scripts/fetch_a_share_financial_statements.py")
            return 1
        rows = sum(len(v) for v in ROIC_YEARS.values())
        print(f"三大报表：{len(ROIC_YEARS)}/{len(codes)} 只、{rows:,} 个财年")
    print(f"历史带重建：{len(codes)} 只｜报告期起点 {args.since}｜g0={args.g0_source}"
          + (f"｜**分档统一为 {args.uniform_tier}**" if args.uniform_tier else "")
          + f"｜逐日状态生效日={args.state_effective}"
          + ("（可得日前一交易日，与生产当晚吸收同构）" if args.state_effective == "prev_trading_day"
             else "（**旧口径：公告日当天**，信号晚生产一个交易日）"))
    if args.notice_cap == "statutory":
        cap = roic_inputs.CAP_STATS
        parts = []
        for label, rows_key, cap_key, unit in (("逐季财务", "financials_rows", "financials_capped", "行"),
                                               ("三大报表", "statements_rows", "statements_capped", "财年")):
            rows, capped = cap.get(rows_key, 0), cap.get(cap_key, 0)
            parts.append(f"{label} {capped:,}/{rows:,} {unit}（{capped / rows:.1%}）" if rows
                         else f"{label} 0 {unit}")
        print("公告日封顶（OI-042，min(记录公告日, 法定截止日)）：" + "｜".join(parts))
    else:
        print("⚠ --notice-cap off：公告日按东财记录日原样（1998-2015 报告期普遍晚一年可用，OI-042），只用于复现旧产物")

    all_bands: list[tuple[str, Band]] = []
    band_rows: list[dict] = []
    daily_counts: dict[str, int] = {}
    price_counts: dict[str, int] = {}

    # **逐日状态边算边写**（2026-08-17）：此前把全部 1,500 万行状态堆成 `list[dict]` 最后一次性
    # `writerows`，在 8 GB 机器上是十几 GB 的驻留——与并发扫描同时跑会把整机打到黑屏（见 CLAUDE.md
    # 「机器资源约束」）。改成开一个句柄流式写，峰值内存与股票数无关，只与单只的天数有关。
    daily_handle = daily_writer = None
    daily_total = 0
    if args.out_daily:
        args.out_daily.parent.mkdir(parents=True, exist_ok=True)
        daily_handle = args.out_daily.open("w", newline="", encoding="utf-8")

    for code in codes:
        series = financials.get(code, {})
        if not series:
            print(f"  ⚠ {code} 无财务数据，跳过")
            continue
        tier = args.uniform_tier or (tiers.get(code) or {}).get("quality_tier") or DEFAULT_TIER
        name = next(iter(series.values()))["security_name"]
        periods = sorted(p for p in series if p >= args.since)
        prices = load_ohlcv(code)
        CURRENT_PRICES.clear()
        if args.wacc_weights == "market":
            CURRENT_PRICES[code] = prices
        bands = [build_band(code, name, tier, series, actions.get(code, []), p, args) for p in periods]
        all_bands.extend((code, b) for b in bands)
        band_rows.extend(band_row(b, tier) for b in bands)
        # OI-074 ③：路径分布统计的原料——每只的最新 ok 带路径、市值代理（末日收盘 × 隐含股本）
        latest_ok = max((b for b in bands if b.status == "ok"),
                        key=lambda b: (b.available_at, b.report_date), default=None)
        if latest_ok is not None and prices:
            mcap = None
            annual_rows = [series[q] for q in sorted(series)
                           if q.endswith("-12-31") and series[q]["notice_date"] <= prices[-1][0]]
            if annual_rows:
                last_row = annual_rows[-1]
                np_, eps_ = _num(last_row.get("parent_netprofit")), _num(last_row.get("basic_eps"))
                if np_ and eps_ and np_ * eps_ > 0:
                    shares = abs(np_ / eps_) * split_factor(actions.get(code, []), last_row["notice_date"], prices[-1][0])
                    mcap = prices[-1][1] * shares
            PATH_STATS.append((code, latest_ok.roic_path or ("equity_fallback" if args.value_model == "roic" else "dcf"),
                               latest_ok.roic_nopat_mode, mcap))
        states = daily_states(code, bands, prices, actions.get(code, []))
        daily_counts[code] = len(states)
        # 分母须与 `daily_states` 用**同一套**可用带（含坑 5 的上市前口径剔除），否则上市前
        # 那几期被正确剔掉后，覆盖率会被算成「缺了一截」而不是「本就不该有」。
        usable = [b for b in applicable_bands(bands) if prices and b.report_date >= prices[0][0]]
        first = usable[0].available_at if usable else None
        price_counts[code] = sum(1 for d, _ in prices if first and d >= first)
        if daily_handle is not None and states:
            if daily_writer is None:
                daily_writer = csv.DictWriter(daily_handle, fieldnames=list(states[0]))
                daily_writer.writeheader()
            daily_writer.writerows(states)
            daily_total += len(states)

    if daily_handle is not None:
        daily_handle.close()
        print(f"逐日状态已写入 {args.out_daily}（{daily_total:,} 行，流式）")
        if EXRIGHT_NEGATIVE:
            print(f"  ⚠ 现金除权调整把带穿到非正值 {len(EXRIGHT_NEGATIVE)} 个 (代码,日)，已跳过须人工看："
                  f"{'、'.join(EXRIGHT_NEGATIVE[:8])}{'…' if len(EXRIGHT_NEGATIVE) > 8 else ''}")

    if args.out_bands:
        args.out_bands.parent.mkdir(parents=True, exist_ok=True)
        with args.out_bands.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=BAND_FIELDS)
            writer.writeheader()
            writer.writerows(band_rows)
        print(f"带已写入 {args.out_bands}（{len(band_rows)} 行）")

    if EXTERNAL_ROE:
        print("外部 ROE 覆盖率：" + "｜".join(f"{k} {v:,}" for k, v in sorted(EXTERNAL_STATS.items())))
    if MOAT_PARAMS:
        print("逐票终值参数覆盖落地：" + "｜".join(f"{k} {v:,}" for k, v in sorted(MOAT_STATS.items())))
    if getattr(args, "dcf_peak_guard", 0):
        print(f"DCF peak 守卫（K={args.dcf_peak_guard:g}）："
              f"跳过单边上抬 {ROIC_STATS.get('DCF peak 守卫·不上抬', 0):,} 带")
    if args.value_model == "roic":
        paths = defaultdict(int)
        for _c, b in all_bands:
            if b.status == "ok":
                paths[b.roic_path or "equity_fallback"] += 1
        total = sum(paths.values()) or 1
        print("ROIC 口径落地路径：" + "｜".join(
            f"{k} {v:,}（{v / total:.1%}）" for k, v in sorted(paths.items())))
        print_path_distribution()
        if ROIC_STATS:
            print("  退回原因：" + "｜".join(f"{k} {v:,}" for k, v in sorted(ROIC_STATS.items())))
        # **退回比例是读结论的前提**：退回的行走的还是旧口径，A/B 差异只来自真正走 ROIC 的那部分
        fallback = paths.get("equity_fallback", 0)
        if fallback / total > 0.30:
            print(f"  ⚠ **{fallback / total:.1%} 的带没走 ROIC 口径**，本轮 A/B 主要在测剩下那部分")
    report(all_bands, daily_counts, price_counts, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
