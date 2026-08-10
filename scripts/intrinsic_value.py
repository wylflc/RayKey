#!/usr/bin/env python3
"""内在价值主模型：ROE—再投资—增长—可分配现金—折现（§6.5.7.1 第一层/第二层）。

来历
----
用户 2026-08-08 给出一套完整计算式（原文标注来自 GPT 5.6），并明确「**并非必须完全按照
这个来，这套计算式是用来参考的，如果有需要修改完善的地方，请修改完善**」。本模块按该
授权实现，并**修正了原式中的一处实质性内部不一致**（见下），其余口径照原式。

原式的核心是对的，且比「净利润 × PEG × 增长率」严谨得多：
增长不是免费的，维持增长 g 需要留存 `b = g/ROE`，故可分配现金 = `E(1 − g/ROE)`。

**修正一：ROE 衰减时 `b_t = g_t/ROE_t` 不成立（本模块的默认口径改了这一条）**
--------------------------------------------------------------------------
原式第 7 节让 `ROE_t` 与 `g_t` **各自独立**地 fade，同时第 2 节又设 `E_t = E_0·Π(1+g_i)`。
在清洁盈余（clean surplus）下这两件事不能同时成立：

    E_t = ROE_t · B_{t-1}
    B_t = B_{t-1} + b_t·E_t = B_{t-1}(1 + ROE_t·b_t)
    ⇒ E_{t+1}/E_t = (ROE_{t+1}/ROE_t)·(1 + ROE_t·b_t)

令它等于 `1+g_{t+1}` 解出**真正需要的留存率**：

    b_t = [ (1+g_{t+1})·ROE_t/ROE_{t+1} − 1 ] / ROE_t          ← 本模块默认

`b_t = g_t/ROE_t` 只是其中 `ROE_{t+1} = ROE_t` 的特例。**ROE 下行时真实所需留存更高、
可分配现金更少，故原式会系统性高估**——而 fade model 的全部意义正是让 ROE 下行，
所以这个偏差恰好发生在原式最想用的场景里。两种口径都实现了（`consistent=True/False`），
差多少由 `--compare` 实测，不靠断言。

**修正二：护栏**
原式未规定 `ROE ≤ 0`、`g ≥ r`、`b > 1`（留存超过利润 = 需外部融资）、`ROE_T ≤ g_T`
（终值留存率 >100%）这些情形怎么办。批量跑 261 只 × 42 个报告期时它们**一定会出现**，
静默产出一个数比报错危险得多（§15.2 第 3 条）。本模块一律显式拒绝并给出原因。

**修正三：内生融资增长约束（`max_retention`，缺省 1.0；2026-08-08 批量实测后加）**
原式让 `ROE_t` 与 `g_t` 各自 fade，两条路径在尾部会打架：ROE 快速下行时，维持既定 g 所需
的留存率会突破 100%。实测后果是显式期现值变**负**：景嘉微 2016 年报（ROE0 46.3%→终值
10%、g0 25%）算出 `min_payout = −196%`、**终值占比 152%**。10 只样本 345 条带里
**26% 出现负派息率**，不是边缘情形。

故缺省 `max_retention=1.0`：留存率触顶时把增速压到内生可支撑的水平
（`g = (ROE_{t+1}/ROE_t)(1+ROE_t·b) − 1`）。`max_retention=None` 可关掉。

**这条约束的名字要准确（2026-08-08 外部评审的正确纠正）**：负 payout **本身不是数学错误**
——现实公司完全可以动用账上净现金、举债或增发来支撑 `g > ROE`。本约束真正的含义是
**「假设增长必须由内生留存自筹、不依赖外部融资」**，这是一个**有意选择的假设**，不是
「不可能的增长」。写清楚是因为它有代价：**账上大量净现金的公司会被这条约束低估**
（它本可以几年内 `再投资 > 净利润` 而无需增发）。更完整的写法是
`再投资_t ≤ E_t + 可动用现金_t + 净举债_t`，第一版为稳健起见只取自筹口径。

**但那个负现值案例仍是真缺陷，与命名无关**：每股口径下把增发款当股东净流出扣掉、却**不同时
计入增发带来的股份稀释**，是会计上的重复计量，而非一个可辩护的假设。修正后负派息率带
**0/377**。

**边界（照原式，写明不做什么）**
原式第 11 节末尾指出：非金融企业更严谨应换 ROIC/NOPAT/FCFF/WACC，金融股才用 ROE+CoE。
**本模块只实现 ROE+CoE 这一支**——批量估值拿不到逐季的 NOPAT、投入资本与债务口径，
硬套 FCFF 只会把假精度堆在缺失的输入上。故本模块定位为 §6.5.7.1 的**第二层（快速估值）**
与第一层的 RI 近似；真要走 FCFF 的公司须逐票建档（§6.5.7）。

用法::

    python3 scripts/intrinsic_value.py --self-test
    python3 scripts/intrinsic_value.py --eps0 5 --roe0 0.25 --g0 0.15 --r 0.10
    python3 scripts/intrinsic_value.py --eps0 5 --roe0 0.25 --g0 0.15 --compare   # 两种留存口径的差
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

# 原式第 8 节：批量估值不假装 r 是一个精确数字，一律出敏感度矩阵。
DEFAULT_R_GRID = (0.08, 0.09, 0.10, 0.11, 0.12)
DEFAULT_N = 10
DEFAULT_G_TERMINAL = 0.03


class ValuationError(ValueError):
    """输入使模型在经济学上无意义时抛出——**不返回一个数**。"""


@dataclass
class ValuationResult:
    intrinsic_value: float          # P0*：每股内在价值
    explicit_pv: float              # 显式预测期现值
    terminal_pv: float              # 终值现值
    implied_pe: float               # P0*/EPS0
    implied_peg: float | None       # implied_pe / (100 g)
    terminal_share: float           # 终值占比——终值占太高说明结论几乎全靠 g_T/ROE_T
    min_payout: float               # 显式期最低派息率，<0 即某年需外部融资
    clamped_years: int              # 因留存率触顶被压低增速的年数（见 max_retention）
    eps_path: list[float]
    roe_path: list[float]
    g_path: list[float]
    payout_path: list[float]


def _fade(x0: float, xt: float, t: int, n: int, lam: float | None) -> float:
    """第 t 年（1..n）的 fade 值。

    线性（原式第 7 节）：`x_t = xT + (x0 − xT)(1 − t/n)`，t=n 时正好落到终值。
    指数（原式给强 moat 公司的选项）：`x_t = xT + (x0 − xT)·e^(−λt)`，λ 越小护城河越久。
    """
    if lam is not None:
        return xt + (x0 - xt) * math.exp(-lam * t)
    return xt + (x0 - xt) * (1 - t / n)


def _required_retention(g_next: float, roe_t: float, roe_next: float, consistent: bool) -> float:
    """支撑「下一年利润增长 g_next」所需的**本年**留存率。

    `consistent=True`（默认，本模块的修正）：`b = [(1+g)·ROE_t/ROE_{t+1} − 1]/ROE_t`。
    `consistent=False`（原式字面）：`b = g/ROE_t`——仅在 ROE 不变时正确。
    """
    if consistent:
        return ((1 + g_next) * roe_t / roe_next - 1) / roe_t
    return g_next / roe_t


def _supportable_growth(retention: float, roe_t: float, roe_next: float, consistent: bool) -> float:
    """`_required_retention` 的反函数：给定留存率，内生能支撑的下一年增长。"""
    if consistent:
        return (roe_next / roe_t) * (1 + roe_t * retention) - 1
    return retention * roe_t


def intrinsic_value(
    eps0: float,
    roe0: float,
    g0: float,
    r: float,
    roe_terminal: float | None = None,
    g_terminal: float = DEFAULT_G_TERMINAL,
    n: int = DEFAULT_N,
    n1: int = 0,
    lam: float | None = None,
    consistent: bool = True,
    g_for_peg: float | None = None,
    max_retention: float | None = 1.0,
    min_retention: float | None = 0.0,
) -> ValuationResult:
    """每股内在价值 P0*（原式第 6 节主公式 + 本模块的留存率修正）。

    稳态特例自检：`ROE0 = ROE_T` 且 `g0 = g_T` 时应精确等于 `EPS0(1+g)(1−g/ROE)/(r−g)`。

    >>> res = intrinsic_value(1.0, 0.20, 0.05, 0.10, roe_terminal=0.20, g_terminal=0.05)
    >>> round(res.intrinsic_value, 6) == round(1.0 * 1.05 * (1 - 0.05 / 0.20) / (0.10 - 0.05), 6)
    True
    >>> round(res.implied_pe, 4)          # PE_TTM = (1+g)(1−g/ROE)/(r−g)
    15.75
    """
    if eps0 <= 0:
        raise ValuationError(f"EPS0={eps0:g} ≤ 0：本模型按盈利折现，亏损公司须走 §6.5.5.2 逐票建档")
    if roe0 <= 0:
        raise ValuationError(f"ROE0={roe0:.2%} ≤ 0：负 ROE 下再投资关系无意义")
    if g_terminal >= r:
        raise ValuationError(f"g_T={g_terminal:.2%} ≥ r={r:.2%}：终值发散（原式第 5 节要求 g_T < r）")
    roe_terminal = roe0 if roe_terminal is None else roe_terminal
    if roe_terminal <= 0:
        raise ValuationError(f"ROE_T={roe_terminal:.2%} ≤ 0")
    if roe_terminal <= g_terminal:
        raise ValuationError(
            f"ROE_T={roe_terminal:.2%} ≤ g_T={g_terminal:.2%}：终值留存率 ≥100%，永续增长无法内生维持")

    # `n1`（用户 2026-08-10）：**高速期年数**——前 n1 年 ROE 与 g 维持起始值不衰减，
    # 其后再按 n 年 fade 到终值。缺省 0，即原行为（g 自第 1 年起即衰减）。
    # 加它的理由是用户的观察「很多公司能保持很多年的高 ROE」，而 n1=0 隐含
    # 「竞争侵蚀从第一年就开始」，对宽护城河公司偏严。**它只改路径形状，不改留存率
    # 一致性、护栏与终值口径**，故 n1=0 时须与旧结果逐位相同（见 --self-test）。
    roe_path = [roe0] * n1 + [_fade(roe0, roe_terminal, t, n, lam) for t in range(1, n + 1)]
    g_path = [g0] * n1 + [_fade(g0, g_terminal, t, n, lam) for t in range(1, n + 1)]
    if any(x <= 0 for x in roe_path):
        raise ValuationError("fade 路径上出现非正 ROE：请检查 ROE_T 或 λ")

    eps_path: list[float] = []
    payout_path: list[float] = []
    realized_g: list[float] = []
    clamped_years = 0
    explicit_pv = 0.0
    eps_prev, roe_prev = eps0, roe0
    for index, (roe_t, g_t) in enumerate(zip(roe_path, g_path), start=1):
        # 本年利润：由「上一年的留存」决定，故先算达成 g_t 所需的上年留存率
        b_prev = _required_retention(g_t, roe_prev, roe_t, consistent)
        if max_retention is not None and b_prev > max_retention:
            # 留存率超过上限 = 该增速须靠外部融资才能实现。**增长受 ROE 约束、不是自由参数**，
            # 故把 g 压到内生可支撑的水平，而不是照发一个需要增发才成立的现金流。
            b_prev = max_retention
            g_t = _supportable_growth(b_prev, roe_prev, roe_t, consistent)
            clamped_years += 1
        elif min_retention is not None and b_prev < min_retention:
            # 反向越界：`ROE_T > ROE_0` 时（低谷公司被假设回升到行业均值）留存率会变成**负数**，
            # 即模型一边让利润增长、一边派息超过利润把净资产派小。这是从假设里凭空生出价值。
            # 实测中国船舶 2019 各期 ROE0 仅 0.24%、终值被设为 r+3%≈10%，隐含 PE 高达 **391**。
            # 与 max_retention 对称处理：把派息压到 100%，增速改由 ROE 回升本身支撑
            # （b=0 时 `g = ROE_{t+1}/ROE_t − 1`，即「利润率修复驱动增长、不靠再投资」）。
            b_prev = min_retention
            g_t = _supportable_growth(b_prev, roe_prev, roe_t, consistent)
            clamped_years += 1
        payout = 1 - b_prev
        eps_t = eps_prev * (1 + g_t)
        pv = eps_t * payout / (1 + r) ** index
        explicit_pv += pv
        eps_path.append(eps_t)
        payout_path.append(payout)
        realized_g.append(g_t)
        eps_prev, roe_prev = eps_t, roe_t
    g_path = realized_g

    # 终值：第 N 年后进入稳态（ROE_T、g_T 恒定），此时 b = g_T/ROE_T 正确无需修正
    payout_terminal = 1 - g_terminal / roe_terminal
    terminal_value = eps_path[-1] * (1 + g_terminal) * payout_terminal / (r - g_terminal)
    # **显式期是 n1 + n 年**，终值须按同一年数折现——只改路径不改这里会把终值高估 (1+r)^n1 倍
    terminal_pv = terminal_value / (1 + r) ** (n1 + n)

    value = explicit_pv + terminal_pv
    peg_growth = g_for_peg if g_for_peg is not None else g0
    return ValuationResult(
        intrinsic_value=value,
        explicit_pv=explicit_pv,
        terminal_pv=terminal_pv,
        implied_pe=value / eps0,
        implied_peg=(value / eps0) / (100 * peg_growth) if peg_growth > 0 else None,
        terminal_share=terminal_pv / value if value else float("nan"),
        min_payout=min(payout_path),
        eps_path=eps_path,
        roe_path=roe_path,
        g_path=g_path,
        payout_path=payout_path,
        clamped_years=clamped_years,
    )


def cost_of_equity(rf: float, erp: float, beta: float = 1.0, rp: float = 0.0) -> float:
    """`r = R_f + β·ERP + RP`（原式第 8 节）。**r 是股权资本成本，不是自定的目标收益率。**

    这条区分是 2026-08-08 用户转来的外部评审最有价值的一点：把「这家公司差、多要点回报」
    塞进 r，会和 §6.2.1 的档位买入规则**重复惩罚同一个风险**。安全边际属于决策层
    （见 `margin_of_safety`），不属于估值层。

    >>> round(cost_of_equity(0.017, 0.0527), 4)
    0.0697
    """
    return rf + beta * erp + rp


def terminal_roe(r: float, excess: float = 0.0) -> float:
    """终值 ROE = `r + 永续超额回报`。

    竞争均衡下无护城河企业的增量回报趋向资本成本，故缺省 `excess=0`。
    **此时终值 PE 恰为 `1/r`**——增长不再创造价值，这正是「ROE = r 时增长无价值」的闭式解，
    也是本函数比「按档位拍一个 ROE_T」更可辩护的原因。要给正超额必须写明护城河证据。

    >>> roe_t = terminal_roe(0.08)
    >>> round(stable_pe_forward(roe_t, 0.02, 0.08), 6) == round(1 / 0.08, 6)
    True
    """
    return r + excess


def terminal_growth_ceiling(rf: float) -> float:
    """永续增长上限 = 无风险利率（Damodaran 稳态硬约束）。

    R_f 已含长期通胀与实际增长预期，故 `g_T > R_f` 等于假设经济永续跑赢无风险利率。
    **这条与「把 r 降到 R_f+ERP」是一套，不能只取前半**：实测 r 由 10% 降到 7.0% 而 g_T
    仍留 3%，P0* 由 10.19 抬到 21.29（**+109%**）；同时把 g_T 拉回 R_f=1.7% 则为 17.88
    （+75%）。**两者之差有三分之一来自那个未经检验的 g_T，而不是来自 r。**
    """
    return rf


def margin_of_safety(intrinsic: float, mos: float) -> float:
    """决策层的买入价上限 = `V·(1 − MOS)`。**与估值层的 r 分开，避免重复惩罚风险。**"""
    return intrinsic * (1 - mos)


def stable_pe_forward(roe: float, g: float, r: float) -> float:
    """原式第 9 节：`PE_forward = (1 − g/ROE)/(r − g)`。

    >>> round(stable_pe_forward(0.20, 0.05, 0.10), 2)
    15.0
    """
    if g >= r:
        raise ValuationError(f"g={g:.2%} ≥ r={r:.2%}")
    if roe <= 0 or g > roe:
        raise ValuationError("ROE 必须为正且 g ≤ ROE")
    return (1 - g / roe) / (r - g)


def stable_pe_ttm(roe: float, g: float, r: float) -> float:
    """原式第 9 节：`PE_TTM = (1+g)(1 − g/ROE)/(r − g)`。分母用 EPS0 而非 EPS1。

    >>> round(stable_pe_ttm(0.20, 0.05, 0.10), 4)
    15.75
    """
    return (1 + g) * stable_pe_forward(roe, g, r)


def stable_peg(roe: float, g: float, r: float) -> float:
    """原式第 10 节：`PEG = (1 − g/ROE)/(100g(r − g))`，g 用小数。

    >>> round(stable_peg(0.20, 0.10, 0.12), 3)
    2.5
    """
    return stable_pe_forward(roe, g, r) / (100 * g)


def valuation_label(market_price: float, intrinsic: float) -> str:
    """原式第 11 节的四档标签。**只作模型标签，不是机械买卖标准**（原文即如此声明）。"""
    ratio = market_price / intrinsic
    if ratio < 0.7:
        return "较大安全边际"
    if ratio < 0.9:
        return "偏低估"
    if ratio <= 1.1:
        return "接近合理价值"
    return "需更乐观假设才支撑"


def sensitivity(eps0: float, roe0: float, g0: float, roe_terminal: float | None = None,
                g_terminal: float = DEFAULT_G_TERMINAL, n: int = DEFAULT_N,
                r_grid=DEFAULT_R_GRID, **kwargs) -> dict[float, ValuationResult | str]:
    """原式第 8 节：同时给多个 r，不假装某个 r 是精确值。"""
    out: dict[float, ValuationResult | str] = {}
    for r in r_grid:
        try:
            out[r] = intrinsic_value(eps0, roe0, g0, r, roe_terminal, g_terminal, n, **kwargs)
        except ValuationError as exc:
            out[r] = f"不可算：{exc}"
    return out


# --------------------------------------------------------------- 自检
def self_test() -> int:
    import doctest
    failures = doctest.testmod(verbose=False).failed
    checks: list[tuple[str, bool]] = []

    # 1. 稳态特例必须精确复现原式第 9 节的闭式解（最强的一条正确性约束）
    for roe, g, r in ((0.20, 0.05, 0.10), (0.30, 0.03, 0.09), (0.12, 0.02, 0.08)):
        res = intrinsic_value(1.0, roe, g, r, roe_terminal=roe, g_terminal=g)
        checks.append((f"稳态 ROE{roe:.0%}/g{g:.0%}/r{r:.0%} 复现闭式 PE_TTM",
                       abs(res.implied_pe - stable_pe_ttm(roe, g, r)) < 1e-9))

    # 2. 两种留存口径：ROE 不变时必须相等，ROE 下行时原式必须偏高
    same = (intrinsic_value(1.0, 0.20, 0.08, 0.10, roe_terminal=0.20, consistent=True).intrinsic_value,
            intrinsic_value(1.0, 0.20, 0.08, 0.10, roe_terminal=0.20, consistent=False).intrinsic_value)
    checks.append(("ROE 恒定时两种留存口径相等", abs(same[0] - same[1]) < 1e-9))
    fading = (intrinsic_value(1.0, 0.30, 0.15, 0.10, roe_terminal=0.12, consistent=True).intrinsic_value,
              intrinsic_value(1.0, 0.30, 0.15, 0.10, roe_terminal=0.12, consistent=False).intrinsic_value)
    checks.append(("ROE 下行时原式口径偏高（本模块修正的方向）", fading[1] > fading[0]))

    # 3. 单调性——**分两种情形，方向相反，两条都要断言**
    #
    # ①ROE 可持续（起始 = 终值）时：ROE 越高价值越高。这是本模型的核心结论。
    sustained = [intrinsic_value(1.0, roe, 0.05, 0.10, roe_terminal=roe, g_terminal=0.05).intrinsic_value
                 for roe in (0.12, 0.15, 0.20, 0.30)]
    checks.append(("可持续 ROE 越高价值越高", all(a < b for a, b in zip(sustained, sustained[1:]))))
    #
    # ②**同一条利润增长路径、同一终值 ROE 下，起始 ROE 越高价值反而越低**（实测 13.25 → 11.74）。
    # 这不是 bug，是本模型一个非平凡的正确推论：要在 ROE 下行的同时维持同样的利润增速，
    # 就必须投入更多资本，可分配现金因此更少。**「高 ROE 一定更值钱」只在 ROE 可持续时成立**——
    # 一旦把 ROE 衰减写进假设，衰减本身就是价值的减项。此前那版自检把①的直觉套到②上，
    # 断言写错而代码是对的。
    decaying = [intrinsic_value(1.0, roe, 0.10, 0.10, roe_terminal=0.15).intrinsic_value
                for roe in (0.15, 0.20, 0.30)]
    checks.append(("同增长路径下 ROE 衰减幅度越大价值越低", all(a > b for a, b in zip(decaying, decaying[1:]))))
    cheap = intrinsic_value(1.0, 0.20, 0.08, 0.12, roe_terminal=0.15).intrinsic_value
    dear = intrinsic_value(1.0, 0.20, 0.08, 0.08, roe_terminal=0.15).intrinsic_value
    checks.append(("r 越高价值越低", dear > cheap))

    # 3b. 修正三：留存率上限。参数取自实测出负现值的那条真实带（景嘉微 2016 年报）。
    unbounded = intrinsic_value(1.0, 0.463, 0.25, 0.13, roe_terminal=0.10, max_retention=None)
    bounded = intrinsic_value(1.0, 0.463, 0.25, 0.13, roe_terminal=0.10)
    checks.append(("无上限时确会出现负派息率（复现实测缺陷）", unbounded.min_payout < 0))
    checks.append(("无上限时显式期现值可为负 → 终值占比 >100%", unbounded.terminal_share > 1.0))
    checks.append(("加上限后派息率恒非负", bounded.min_payout >= -1e-12))
    checks.append(("加上限后终值占比落回 (0,1]", 0 < bounded.terminal_share <= 1.0))
    checks.append(("上限确实生效并记录了受限年数", bounded.clamped_years > 0))
    # 方向是**上限后价值更高**（实测 4.614 → 5.703），且这是对的：无上限那版把「需要增发才
    # 能实现的增长」当成股东掏出的现金逐年折现（显式期现值 −2.421），等于对股东罚了一笔他们
    # 本会换到股份的钱。上限去掉的是这个虚假罚项，不是把负值粉饰掉——终值同时由 7.035 降到
    # 4.505（增速被压低，EPS_N 由 3.312 降到 2.121），两侧都动了才是真修正。
    checks.append(("上限去掉的是虚假罚项：显式期由负转正", unbounded.explicit_pv < 0 < bounded.explicit_pv))
    checks.append(("同时终值被压低（增速确实降了，不是单边抬价）",
                   bounded.terminal_pv < unbounded.terminal_pv))
    # 不触顶的常规参数下，上限必须**完全不改变**结果——否则就是默默改了所有带
    for kwargs in ({"roe_terminal": 0.20, "g_terminal": 0.05}, {"roe_terminal": 0.15}):
        with_cap = intrinsic_value(1.0, 0.20, 0.05, 0.10, **kwargs).intrinsic_value
        without = intrinsic_value(1.0, 0.20, 0.05, 0.10, max_retention=None, **kwargs).intrinsic_value
        checks.append((f"未触顶时上限不改变结果 {kwargs}", abs(with_cap - without) < 1e-12))

    # 4. 护栏必须报错而不是给个数
    def raises(fn) -> bool:
        try:
            fn()
        except ValuationError:
            return True
        return False
    checks.append(("g_T ≥ r 报错", raises(lambda: intrinsic_value(1.0, 0.2, 0.05, 0.08, g_terminal=0.08))))
    checks.append(("ROE_T ≤ g_T 报错", raises(lambda: intrinsic_value(1.0, 0.2, 0.05, 0.10, roe_terminal=0.02))))
    checks.append(("EPS0 ≤ 0 报错", raises(lambda: intrinsic_value(-1.0, 0.2, 0.05, 0.10))))
    checks.append(("ROE0 ≤ 0 报错", raises(lambda: intrinsic_value(1.0, -0.2, 0.05, 0.10))))

    # 5. PEG 必须随 ROE 单调上升（OI-023 的原始诉求）
    pegs = [stable_peg(roe, 0.10, 0.11) for roe in (0.12, 0.15, 0.20, 0.25, 0.30)]
    # 5. r 与终值的一致性（2026-08-08 外部评审引入的口径）
    checks.append(("CoE 复现 R_f+βERP", abs(cost_of_equity(0.017, 0.0527) - 0.0697) < 1e-9))
    # ROE_T = r 时终值 PE 必须恰为 1/r —— 「ROE=r 时增长不创造价值」的闭式解
    for r in (0.07, 0.08, 0.10):
        checks.append((f"ROE_T=r={r:.0%} 时终值 PE = 1/r",
                       abs(stable_pe_forward(terminal_roe(r), 0.02, r) - 1 / r) < 1e-9))
    # g_T ≤ R_f 这条硬约束值多少钱——数字入自检，免得日后被当成可选项省掉
    low = intrinsic_value(1.0, 0.25, 0.12, 0.07, roe_terminal=0.12, g_terminal=0.017).intrinsic_value
    high = intrinsic_value(1.0, 0.25, 0.12, 0.07, roe_terminal=0.12, g_terminal=0.030).intrinsic_value
    checks.append(("g_T 由 R_f 放宽到 3% 会显著抬高估值（故不可只降 r 不管 g_T）",
                   high / low > 1.15))
    checks.append(("稳态 PEG 随 ROE 单调上升", all(a < b for a, b in zip(pegs, pegs[1:]))))

    # 6. 终值占比必须在 (0,1)
    res = intrinsic_value(1.0, 0.25, 0.12, 0.10, roe_terminal=0.13)
    checks.append(("终值占比落在 (0,1)", 0 < res.terminal_share < 1))

    for label, ok in checks:
        print(f"  {'✅' if ok else '❌'} {label}")
        failures += 0 if ok else 1
    print(f"自检 {len(checks)} 项 + doctest，失败 {failures} 项")
    return 1 if failures else 0


def compare_retention(eps0: float, roe0: float, g0: float, r: float,
                      roe_terminal: float, g_terminal: float, n: int) -> None:
    """实测两种留存口径的差——**不靠断言，靠数字**。"""
    print(f"\n留存率口径对照（EPS0={eps0:g}｜ROE {roe0:.0%}→{roe_terminal:.0%}｜"
          f"g {g0:.0%}→{g_terminal:.0%}｜r={r:.0%}｜N={n}）")
    fixed = intrinsic_value(eps0, roe0, g0, r, roe_terminal, g_terminal, n, consistent=False)
    fixed_ok = intrinsic_value(eps0, roe0, g0, r, roe_terminal, g_terminal, n, consistent=True)
    gap = fixed.intrinsic_value / fixed_ok.intrinsic_value - 1
    print(f"  原式 b=g/ROE          价值 {fixed.intrinsic_value:>9.2f}｜隐含PE {fixed.implied_pe:>6.1f}"
          f"｜显式期最低派息率 {fixed.min_payout:>7.1%}")
    print(f"  修正 b=[(1+g)ROEt/ROEt+1−1]/ROEt  价值 {fixed_ok.intrinsic_value:>9.2f}"
          f"｜隐含PE {fixed_ok.implied_pe:>6.1f}｜显式期最低派息率 {fixed_ok.min_payout:>7.1%}")
    print(f"  **原式高估 {gap:+.1%}**" if gap > 0 else f"  差异 {gap:+.1%}")


def main() -> int:
    parser = argparse.ArgumentParser(description="内在价值主模型（ROE—再投资—增长—折现）")
    parser.add_argument("--eps0", type=float)
    parser.add_argument("--roe0", type=float)
    parser.add_argument("--g0", type=float)
    parser.add_argument("--r", type=float, default=0.10)
    parser.add_argument("--roe-terminal", type=float)
    parser.add_argument("--g-terminal", type=float, default=DEFAULT_G_TERMINAL)
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    parser.add_argument("--lam", type=float, help="指数 fade 的 λ（缺省用线性 fade）")
    parser.add_argument("--price", type=float, help="当前股价，给出即打印估值标签")
    parser.add_argument("--legacy-retention", action="store_true", help="用原式的 b=g/ROE")
    parser.add_argument("--compare", action="store_true", help="对照两种留存口径")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.eps0 is None or args.roe0 is None or args.g0 is None:
        parser.error("需要 --eps0 --roe0 --g0（或用 --self-test）")

    roe_t = args.roe_terminal if args.roe_terminal is not None else max(args.r + 0.02, args.roe0 / 2)
    if args.compare:
        compare_retention(args.eps0, args.roe0, args.g0, args.r, roe_t, args.g_terminal, args.n)
        return 0

    res = intrinsic_value(args.eps0, args.roe0, args.g0, args.r, roe_t, args.g_terminal,
                          args.n, args.lam, consistent=not args.legacy_retention)
    print(f"内在价值 P0* = **{res.intrinsic_value:.2f}**｜隐含 PE {res.implied_pe:.1f}"
          + (f"｜隐含 PEG {res.implied_peg:.2f}" if res.implied_peg else ""))
    print(f"  显式期现值 {res.explicit_pv:.2f}（{1 - res.terminal_share:.0%}）"
          f"｜终值现值 {res.terminal_pv:.2f}（**{res.terminal_share:.0%}**）")
    if res.terminal_share > 0.75:
        print("  ⚠ 终值占比 >75%：结论几乎全部由 g_T/ROE_T 决定，显式期算得再细也没用")
    if res.min_payout < 0:
        print(f"  ⚠ 显式期最低派息率 {res.min_payout:.1%} < 0：该增长路径需外部融资才能维持")
    if args.price:
        print(f"  现价 {args.price:g} → 价格/内在价值 {args.price / res.intrinsic_value:.2f}"
              f"｜**{valuation_label(args.price, res.intrinsic_value)}**")

    print(f"\n对 r 的敏感度（原式第 8 节：不假装 r 是精确值）")
    print(f"  {'r':>6}{'P0*':>12}{'隐含PE':>10}{'终值占比':>10}")
    for r, item in sensitivity(args.eps0, args.roe0, args.g0, roe_t, args.g_terminal, args.n,
                               lam=args.lam, consistent=not args.legacy_retention).items():
        if isinstance(item, str):
            print(f"  {r:>5.0%}  {item}")
        else:
            print(f"  {r:>5.0%}{item.intrinsic_value:>12.2f}{item.implied_pe:>10.1f}{item.terminal_share:>10.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
