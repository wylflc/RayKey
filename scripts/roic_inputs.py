#!/usr/bin/env python3
"""从三大报表推导 ROIC / FCFF 口径的估值输入（「All Money Is Equal」框架 §2~§4）。

与 §12.65 第一版的区别
----------------------
第一版（`--value-model ame`）只有每股经营现金流可用，于是拿它当 Owner Earnings。
**经营现金流加回了折旧摊销却没有扣资本开支**，对重资产公司系统性偏高，实测把神火／中石油／
陕煤／神华／海螺加进组合、把银行与消费医药砍掉——**与缺口方向逐一对应**，所以那一版
测出的不是「按现金比较是否更好」，而是「把折旧当成现金会怎样」。

本模块用 `data/raw/financials_statements/` 的三大报表把缺口补上，实现框架的**本来面目**：

    NOPAT = EBIT × (1 − t)                          EBIT = 利润总额 + 利息费用
    投入资本 IC = 有息负债 + 股东权益 − 超额现金
    ROIC = NOPAT / IC                               增量 ROIC = ΔNOPAT / ΔIC
    再投资率 RR = (资本开支 − 折旧摊销 + ΔWC) / NOPAT
    g = ROIC × RR                                   FCFF = NOPAT × (1 − RR)
    EV/NOPAT 终值 = (1 − g_T/ROIC_T) / (WACC − g_T)

**金融企业不走这条路**：框架 §6 明写金融企业用权益口径 `g = ROE×b`、`PB=(ROE−g)/(r−g)`，
因为对银行/保险而言「有息负债」是经营性负债、投入资本无经济意义。故本模块对
`org_table` 落在 `B*`/`S*`/`I*` 的公司返回 `None`，由调用方退回现行权益 DCF。

口径选择与它们的代价
--------------------
* **账面权重算 WACC**：`WACC = (E·re + D·rd·(1−t))/(E+D)` 里的 `E` 用账面净资产而非市值。
  用市值会**循环**（估值依赖 WACC、WACC 依赖市值），标准解法是迭代或用目标结构；
  这里取账面权重，代价是高市净率公司的股权权重被低估、WACC 偏低（偏乐观）。
* **维持性资本开支 ≈ 折旧摊销**：框架要的是「维持竞争地位所需」的那部分，报表不单独披露。
  折旧摊销是最常用的代理（Buffett 原文即用它），代价是高增长期公司的扩张性开支
  会被算成再投资（正确）、而通胀期的重置成本高于历史成本折旧（低估维持开支，偏乐观）。
* **超额现金 = max(0, 货币资金 + 交易性金融资产 − 2%×营收)**：2% 是营运现金的通行经验值。
* **2019 年前没有单列的利息费用**：`FE_INTEREST_EXPENSE` 实测只覆盖 30% 的财年（新准则才单列），
  其余年份退回**财务费用净额**且负值取 0。财务费用净额已扣利息收入，故对现金多的公司
  会低估利息费用——但这类公司本就几乎无息负债，`EBIT ≈ 利润总额` 恰好是对的；
  真正受影响的是「既有大额存款又有大额借款」的公司，其 EBIT 会被低估、ROIC 偏低（偏保守）。
"""
from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STMT_DIR = ROOT / "data/raw/financials_statements"

OPERATING_CASH_RATIO = 0.02      # 营运现金 ≈ 2% 营收，其余视为超额现金
DEFAULT_TAX_RATE = 0.25          # 法定税率，利润总额非正时回退
TAX_RATE_BOUNDS = (0.0, 0.40)
COST_OF_DEBT_BOUNDS = (0.02, 0.12)
DEFAULT_COST_OF_DEBT = 0.045

# 有息负债的构成。租赁负债计入（新准则下经营租赁上表，不计会低估重资产零售/航空的杠杆）。
DEBT_FIELDS = ("SHORT_LOAN", "SHORT_BOND_PAYABLE", "NONCURRENT_LIAB_1YEAR",
               "LONG_LOAN", "BOND_PAYABLE", "LEASE_LIAB", "PERPETUAL_BOND_PAYBALE")
# 折旧摊销四项。**不含 `OILGAS_BIOLOGY_DEPR`／`IR_DEPR`**——实测海螺水泥 2024
# `FA_IR_DEPR`=7,214,312,412 恰等于 `OILGAS`(7,210,685,487)+`IR_DEPR`(3,626,925)，
# 即 `FA_IR_DEPR` 是**父项合计**，再加子项就是重复计。
DEPR_FIELDS = ("FA_IR_DEPR", "IA_AMORTIZE", "LPE_AMORTIZE", "USERIGHT_ASSET_AMORTIZE")
# 经营性营运资金。用资产负债表存量差分而非现金流量表的加回项——后者在并购年份会混入
# 合并范围变动，存量差分同样会但至少口径单一、可复核。
WC_ASSET_FIELDS = ("INVENTORY", "ACCOUNTS_RECE", "NOTE_ACCOUNTS_RECE", "NOTE_RECE",
                   "PREPAYMENT", "CONTRACT_ASSET")
WC_LIAB_FIELDS = ("ACCOUNTS_PAYABLE", "NOTE_ACCOUNTS_PAYABLE", "NOTE_PAYABLE",
                  "ADVANCE_RECEIVABLES", "CONTRACT_LIAB", "TAX_PAYABLE",
                  "STAFF_SALARY_PAYABLE")

FINANCIAL_TABLE_PREFIXES = ("RPT_F10_FINANCE_B", "RPT_F10_FINANCE_S", "RPT_F10_FINANCE_I")


def _num(value) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum(row: dict, fields) -> float:
    """字段求和，缺失记 0。**缺失与零在报表里同义**（东财对未披露项留空）。"""
    return sum(_num(row.get(f)) or 0.0 for f in fields)


@dataclass
class RoicYear:
    """单个财年的 ROIC 口径输入。全部为**总额**（元），不是每股。"""
    period: str
    notice_date: str
    ebit: float | None = None
    tax_rate: float | None = None
    nopat: float | None = None
    invested_capital: float | None = None
    interest_debt: float = 0.0
    excess_cash: float = 0.0
    minority_equity: float = 0.0
    total_equity: float | None = None
    parent_equity: float | None = None
    revenue: float | None = None
    capex: float = 0.0
    dep_amort: float = 0.0
    working_capital: float | None = None
    cfo: float | None = None
    interest_expense: float = 0.0
    is_financial: bool = False
    tax_rate_observed: bool = False   # True=税率来自本期 所得税/利润总额；False=利润总额非正时回退法定税率


def load_statements(codes: set[str] | None = None,
                    stmt_dir: Path = STMT_DIR,
                    ic_floor: float = 0.0) -> dict[str, dict[str, RoicYear]]:
    """读三大报表 → `{代码: {财年: RoicYear}}`。缺表即返回空，由调用方降级。

    `ic_floor`：投入资本下限 = `ic_floor × 总权益`。**v1 缺省 0（不启用）**。
    动机（§12.67 锚点诊断）：`IC = 有息负债 + 权益 − 超额现金` 对现金极厚的公司会趋零，
    ROIC 随之发散——实测格力 2018 报 **793.7%**，全池 4.0% 的带 ROIC0 > 100%，
    恰集中在格力×40、五粮液×31、茅台×24 这批现金最厚的名字。分母趋零后
    ROIC、增量 ROIC、ΔIC 全部失真。下限取「权益的一个比例」而非常数，保持无量纲。"""
    raw: dict[str, dict[str, dict[str, dict]]] = {}
    for kind in ("balance", "income", "cashflow"):
        path = stmt_dir / f"{kind}.csv"
        if not path.exists():
            return {}
        with path.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                code = (row.get("security_code") or "").zfill(6)
                if codes is not None and code not in codes:
                    continue
                period = (row.get("REPORT_DATE") or "")[:10]
                if not period.endswith("-12-31"):
                    continue
                raw.setdefault(code, {}).setdefault(period, {})[kind] = row

    out: dict[str, dict[str, RoicYear]] = {}
    for code, periods in raw.items():
        for period, parts in periods.items():
            bal, inc, cfl = parts.get("balance"), parts.get("income"), parts.get("cashflow")
            if not (bal and inc):
                continue
            # 公告日取三表最晚——三表同属一份年报，但东财偶有单表 notice 缺失/提前
            notice = max((p.get("NOTICE_DATE") or "")[:10] for p in parts.values())
            if not notice:
                continue
            year = RoicYear(period=period, notice_date=notice)
            year.is_financial = any(
                (p.get("org_table") or "").startswith(FINANCIAL_TABLE_PREFIXES)
                for p in parts.values())
            year.revenue = _num(inc.get("TOTAL_OPERATE_INCOME"))
            year.total_equity = _num(bal.get("TOTAL_EQUITY"))
            year.parent_equity = _num(bal.get("TOTAL_PARENT_EQUITY"))
            year.minority_equity = _num(bal.get("MINORITY_EQUITY")) or 0.0
            year.interest_debt = _sum(bal, DEBT_FIELDS)
            # 利息费用：新准则单列 `FE_INTEREST_EXPENSE`，早年只有财务费用净额
            year.interest_expense = (_num(inc.get("FE_INTEREST_EXPENSE"))
                                     or max(_num(inc.get("FINANCE_EXPENSE")) or 0.0, 0.0))
            total_profit = _num(inc.get("TOTAL_PROFIT"))
            income_tax = _num(inc.get("INCOME_TAX"))
            if total_profit is not None:
                year.ebit = total_profit + year.interest_expense
                if total_profit > 0 and income_tax is not None:
                    rate = income_tax / total_profit
                    lo, hi = TAX_RATE_BOUNDS
                    year.tax_rate = min(max(rate, lo), hi)
                    year.tax_rate_observed = True
                else:
                    year.tax_rate = DEFAULT_TAX_RATE
                year.nopat = year.ebit * (1 - year.tax_rate)
            cash = (_num(bal.get("MONETARYFUNDS")) or 0.0) \
                + (_num(bal.get("TRADE_FINASSET")) or 0.0) \
                + (_num(bal.get("TRADE_FINASSET_NOTFVTPL")) or 0.0)
            operating_cash = OPERATING_CASH_RATIO * (year.revenue or 0.0)
            year.excess_cash = max(0.0, cash - operating_cash)
            if year.total_equity is not None:
                ic = year.interest_debt + year.total_equity - year.excess_cash
                if ic_floor > 0:
                    ic = max(ic, ic_floor * year.total_equity)
                year.invested_capital = ic if ic > 0 else None
            year.working_capital = _sum(bal, WC_ASSET_FIELDS) - _sum(bal, WC_LIAB_FIELDS)
            if cfl:
                year.capex = _num(cfl.get("CONSTRUCT_LONG_ASSET")) or 0.0
                year.dep_amort = _sum(cfl, DEPR_FIELDS)
                year.cfo = _num(cfl.get("NETCASH_OPERATE"))
            out.setdefault(code, {})[period] = year
    return out


def years_before(years: dict[str, RoicYear], available_at: str, count: int) -> list[RoicYear]:
    """公告日 ≤ `available_at` 的最近 `count` 个财年，**降序**（与建带模块同规）。"""
    usable = [y for y in years.values() if y.notice_date and y.notice_date <= available_at]
    return sorted(usable, key=lambda y: y.period, reverse=True)[:count]


def roic_of(year: RoicYear, prev: RoicYear | None) -> float | None:
    """`NOPAT / 平均投入资本`。首年无上期时退回期末投入资本。"""
    if year.nopat is None or year.invested_capital is None:
        return None
    base = year.invested_capital
    if prev is not None and prev.invested_capital:
        base = (year.invested_capital + prev.invested_capital) / 2
    return year.nopat / base if base > 0 else None


def normalized_roic(history: list[RoicYear]) -> float | None:
    """近若干年 ROIC 的中位——与建带模块的归一化 ROE 同规（不外推单年低谷/高点）。"""
    ordered = sorted(history, key=lambda y: y.period)
    values = [r for r in (roic_of(y, ordered[i - 1] if i else None)
                          for i, y in enumerate(ordered)) if r is not None]
    return statistics.median(values) if values else None


def incremental_roic(history: list[RoicYear]) -> float | None:
    """`ΔNOPAT / ΔIC`——**新投的一块钱多赚回多少**（框架 §4：比存量 ROIC 更要紧）。

    投入资本未净增长时无定义（回购/减值把 IC 打薄，此时比值的符号没有经济含义）。
    """
    ordered = sorted(history, key=lambda y: y.period)
    if len(ordered) < 2:
        return None
    new, old = ordered[-1], ordered[0]
    if None in (new.nopat, old.nopat, new.invested_capital, old.invested_capital):
        return None
    delta_ic = new.invested_capital - old.invested_capital
    if delta_ic <= 0:
        return None
    return (new.nopat - old.nopat) / delta_ic


def incremental_roic_multiwindow(history: list[RoicYear],
                                 spans: tuple[int, ...] = (3, 5, 7)) -> float | None:
    """多窗口稳健中位的增量 ROIC（OI-069 第 2 条候选，研究开关；§12.100 实测回测中性但不压噪声，不采纳）。

    现行 `incremental_roic` 只看窗口首尾两点，任一端点被营运资金波动、并购、资本开支时间
    错位或 ΔIC 趋零污染，读数就整段失真（全历史相邻年报带 |Δ增量ROIC| 中位 7.8pp、P90 59.5pp、
    符号翻转 10.6%，回测日志 §12.99.1）。本函数对**同一终点、不同起点**的几个窗口（缺省 3/5/7 年，
    历史不足时取可用年数）各算一次首尾 `ΔNOPAT/ΔIC`，只保留 ΔIC>0 的窗口，取**中位**——
    单个坏端点最多毁掉一个窗口。窗口全部无定义时仍返回 None（语义与现行一致：资本腿不可算）。
    `history` 须按调用方要求含更长的回看（建带侧给 `--roic-iroic-years`，缺省 7 年）。
    """
    ordered = [y for y in sorted(history, key=lambda y: y.period)
               if y.nopat is not None and y.invested_capital is not None]
    n = len(ordered)
    if n < 2:
        return None
    values = []
    for span in sorted({min(s, n) for s in spans}):
        if span < 2:
            continue
        new, old = ordered[-1], ordered[-span]
        delta_ic = new.invested_capital - old.invested_capital
        if delta_ic <= 0:
            continue
        values.append((new.nopat - old.nopat) / delta_ic)
    return statistics.median(values) if values else None


def incremental_roic_allpairs(history: list[RoicYear]) -> float | None:
    """全对中位的增量 ROIC（OI-069 第 2 条候选，研究开关；§12.100 实测不采纳）。

    窗口内**任意两个财年** (i<j) 各算一次 `ΔNOPAT/ΔIC`（只保留 ΔIC>0 的对），取中位。与同终点多窗口
    （`incremental_roic_multiwindow`）的区别：最新一年只参与 n−1 对而非全部窗口，单个坏端点——无论在
    窗口哪一端——最多污染少数几对。§12.100.2 按报表实测（4,298 条年报带）：相邻年 |Δ| 中位 7.8pp→4.4pp、
    P90 60pp→34pp、符号翻转 10.7%→5.6%，水平中位 0.189→0.194——**估计量本身**噪声减半、水平不动；但经
    `g0 = max(资本腿, 增速腿)` 的凸性，重估只会把 trailing 来源的带往上推、把负 iROIC 翻成可用，
    全市场 3,359 条带 g0 变动、2,332 条上调，23 起点滚5 −0.74pp（8/23）——按「不影响收益率」原则不采纳。
    窗口由调用方给（建带侧 `--roic-iroic-years`，缺省 7 年）。
    """
    ordered = [y for y in sorted(history, key=lambda y: y.period)
               if y.nopat is not None and y.invested_capital is not None]
    values = []
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            delta_ic = ordered[j].invested_capital - ordered[i].invested_capital
            if delta_ic > 0:
                values.append((ordered[j].nopat - ordered[i].nopat) / delta_ic)
    return statistics.median(values) if values else None


def incremental_roic_allpairs_guarded(history: list[RoicYear], base_years: int = 5) -> float | None:
    """保覆盖的全对中位：只在**现行首尾口径可算**（近 `base_years` 年 ΔIC>0）时给出全对中位，否则仍 None。

    §12.100.3 实测：不保覆盖的 `allpairs` 把 740 条 `ΔIC≤0` 的带从「资本腿不可算」变成可算、g0 由 0 上调，
    叠加 `max(资本腿, 增速腿)` 的凸性，整体抬高 g0 水平（3,359 条带变动、2,332 条上调），滚5 −0.74pp；
    本函数把覆盖钉在现行集合上，只替换可算处的估计值，隔离「压噪声」与「扩覆盖」两个效应。
    实测仍 −0.72pp（8/23）：612 条带的 iROIC 由负转正、670 条资本腿升到增速腿之上，g0 只升不降——不采纳。
    """
    ordered = sorted(history, key=lambda y: y.period)
    if incremental_roic(ordered[-base_years:]) is None:
        return None
    return incremental_roic_allpairs(history)


def incremental_roic_regression(history: list[RoicYear], min_pairs: int = 3) -> float | None:
    """回归口径的增量 ROIC：对窗口内逐年 `ΔNOPAT_t = α + β·ΔIC_t` 做 OLS，取 β（OI-069 第 2 条候选之二）。

    每对相邻年份贡献一个点，≥ `min_pairs` 对且 ΔIC 有离散度才可算；β 可为负（由调用方按
    `iroic > 0` 决定资本腿是否启用，与现行同规）。样本只有 4~6 个点，β 对离群年敏感，
    故与多窗口中位并列实测而非直接采用。
    """
    ordered = [y for y in sorted(history, key=lambda y: y.period)
               if y.nopat is not None and y.invested_capital is not None]
    pairs = [(b.invested_capital - a.invested_capital, b.nopat - a.nopat)
             for a, b in zip(ordered, ordered[1:])]
    if len(pairs) < min_pairs:
        return None
    mx = statistics.mean(x for x, _ in pairs)
    my = statistics.mean(y for _, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    if sxx <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    return sxy / sxx


def normalized_tax_rate(history: list[RoicYear]) -> float | None:
    """窗口内**实际观测到**的年度税率（所得税/利润总额，已夹 [0,40%]）的中位（OI-069 第 5 条候选，研究开关）。

    单期税率受递延税、一次性优惠、亏损年回退法定税率污染（§12.99.1：相邻年报带 |Δ税率| 中位 1.2pp、
    P90 6.8pp）。取多年中位只压噪声、不移均值；但统一税率重算各年 NOPAT 等于把利润增速腿改成 EBIT 增速，
    §12.100 实测 23 起点滚5 −3.31pp（5/23）、滚3回撤 39.1→41.5，不采纳。窗口内没有一个观测年时返回 None，
    调用方保持现行逐年税率。
    """
    rates = [y.tax_rate for y in history if y.tax_rate_observed and y.tax_rate is not None]
    return statistics.median(rates) if rates else None


def with_tax_rate(history: list[RoicYear], tax_rate: float) -> list[RoicYear]:
    """按统一税率重算每年 `NOPAT = EBIT × (1 − t)`，**返回副本**（`ROIC_YEARS` 在各时点的带之间共享，不可原地改）。"""
    out = []
    for y in history:
        if y.ebit is None:
            out.append(y)
            continue
        out.append(replace(y, tax_rate=tax_rate, nopat=y.ebit * (1 - tax_rate)))
    return out


def trailing_nopat_cagr(history: list[RoicYear], min_years: int = 3) -> float | None:
    """窗口内**总额 NOPAT** 的年化增速，端点各取两年均值抗单年噪声。

    为什么需要它（§12.67 锚点诊断）：`g = 增量ROIC × 再投资率` 只度量**资本驱动**的增长。
    对最好的生意——提价、品牌、负营运资金——利润在净再投资约为零甚至为负时照样增长
    （茅台 2018 窗口 RR=−16.6%、格力 −45.9%、宁德 2021 −232%），资本口径把它们的 g 判成 0，
    于是在 2019-04 这类公认买点上把茅台/五粮液/老窖全部读成「高估」。
    利润增长本身是资本自由增长的直接观测，两条腿取大（调用方负责）。

    总额而非每股：增发/回购的稀释效应属于「每股」层，本函数量的是生意本身的增速；
    每股修正由估值层的 BPS 基准完成。端点须为正，跨度不足 `min_years` 年返回 None。
    """
    ordered = [y for y in sorted(history, key=lambda x: x.period) if y.nopat is not None]
    if len(ordered) < min_years + 1:
        return None
    head = [y.nopat for y in ordered[:2]]
    tail = [y.nopat for y in ordered[-2:]]
    begin, end = statistics.mean(head), statistics.mean(tail)
    span = (int(ordered[-1].period[:4]) + int(ordered[-2].period[:4])
            - int(ordered[0].period[:4]) - int(ordered[1].period[:4])) / 2
    if begin <= 0 or end <= 0 or span < min_years - 1:
        return None
    return (end / begin) ** (1 / span) - 1


def reinvestment_rate(history: list[RoicYear]) -> float | None:
    """`(资本开支 − 折旧摊销 + ΔWC) / NOPAT`，按窗口合计而非单年（单年噪声极大）。"""
    ordered = sorted(history, key=lambda y: y.period)
    if len(ordered) < 2:
        return None
    nopat_sum = sum(y.nopat for y in ordered[1:] if y.nopat is not None)
    if nopat_sum <= 0:
        return None
    capex_sum = sum(y.capex for y in ordered[1:])
    depr_sum = sum(y.dep_amort for y in ordered[1:])
    delta_wc = 0.0
    if ordered[0].working_capital is not None and ordered[-1].working_capital is not None:
        delta_wc = ordered[-1].working_capital - ordered[0].working_capital
    return (capex_sum - depr_sum + delta_wc) / nopat_sum


def cost_of_debt(history: list[RoicYear]) -> float:
    """`利息费用 / 平均有息负债`，夹在 [2%, 12%]。无债或不可算时回退 4.5%。"""
    ordered = sorted(history, key=lambda y: y.period)
    interest = sum(y.interest_expense for y in ordered[1:])
    debts = [y.interest_debt for y in ordered if y.interest_debt > 0]
    if not debts or interest <= 0 or len(ordered) < 2:
        return DEFAULT_COST_OF_DEBT
    avg_debt = statistics.mean(debts)
    if avg_debt <= 0:
        return DEFAULT_COST_OF_DEBT
    lo, hi = COST_OF_DEBT_BOUNDS
    return min(max(interest / (len(ordered) - 1) / avg_debt, lo), hi)


def wacc(cost_equity: float, cost_debt: float, tax_rate: float,
         equity: float, debt: float) -> float:
    """`(E·re + D·rd·(1−t)) / (E+D)`，**账面权重**（用市值会循环，见模块头）。"""
    total = equity + debt
    if total <= 0 or equity <= 0:
        return cost_equity
    return (equity * cost_equity + debt * cost_debt * (1 - tax_rate)) / total
