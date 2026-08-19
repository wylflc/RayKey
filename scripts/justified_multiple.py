#!/usr/bin/env python3
"""合理倍数（justified multiple）：由 ROE、增长、要求回报推出 PE，PEG 降为输出（OI-023）。

登记的缺陷
----------
§6.5.2 写着「PEG（按 ROE 修正）：PEG 随 ROE 上移（OI-005 判据）」，但全池实测**这条梯度
不存在**：按 ROE 分档的 PEG 中位为 ≥25% 档 **1.00**（n=11）／20-25% 档 1.10（n=8）／
15-20% 档 1.10（n=14）／<15% 档 **1.00**（n=21）——不但不单调，最高 ROE 档反而取了最低的
PEG 中位；全池 84/148 家直接取 1.0，更像默认值而非推导结果。

用户 2026-08-07 裁定（要点）
---------------------------
> 更严谨的做法不是"先定一个 PEG，再乘利润"，而是先从企业经济学关系推导出**合理 PE /
> PB / EV multiple**，PEG 只作为结果校验。……**PE、PEG 应该成为模型输出，而不是输入。**

采纳为**三层估值体系**：

| 层级 | 方法 | 用途 |
| --- | --- | --- |
| 第一层 | DCF / Residual Income | 核心 intrinsic value |
| **第二层** | **Justified PE/PB** | 快速估值（本模块） |
| 第三层 | PEG / 历史 PE 分位 | sanity check（**只作校验，不再作输入**） |

本模块实现第二层，并把第三层的 PEG 变成由第二层反算出来的**输出**。

核心关系
--------
增长不是免费的——维持增长 g 需要留存率 ``b = g / ROE``，故派息率 ``1 − g/ROE``：

    PE_justified = (1 − g/ROE) / (r − g)

它同时含增长率、ROE、资本消耗与要求回报，而 PEG 只含增长率。两家同为 g=8%、r=10% 的公司：
ROE=12% → PE 16.7；ROE=30% → PE 36.7。**这就是「PEG 应随 ROE 上移」的理论来源**——但正确
的做法不是给 PEG 排一张档位表，而是根本不把 PEG 当输入。

⚠ **单阶段戈登只在接近稳态时成立**，且在 ``g → r`` 时对 PE 极度敏感（分母 ``r − g`` 趋零）。
高增长期不得直接永久外推——这正是 §6.8 已经踩过的坑（首版对美团取 g=8% 而 r=8.5%，分母只剩
0.5pp，带被放大到现价的四倍）。故本模块同时提供 ``fade_pe``：高增长 n1 年 → 线性衰减 n2 年
→ 永续 g∞，且 ROE 同步向终值回落（竞争最终压低超额 ROE）。

用法::

    python3 scripts/justified_multiple.py --grid                 # ROE × g 的合理 PE 与隐含 PEG 网格
    python3 scripts/justified_multiple.py --roe 0.25 --g 0.12 --r 0.10
    python3 scripts/justified_multiple.py --self-test
"""
from __future__ import annotations

import argparse

# §6.8 已成文的账户级要求回报（跨市场统一，机会成本口径）。A 股侧按公司质量分档见下表，
# **不是精确数字，是必须做敏感度的假设**（用户裁定原文）。
REQUIRED_RETURN_BY_QUALITY = {
    "极优质低风险龙头": (0.07, 0.09),
    "优质成熟公司": (0.09, 0.11),
    "普通周期/制造业": (0.10, 0.13),
    "高风险成长公司": (0.12, 0.16),
}

TERMINAL_GROWTH_DEFAULT = 0.03


def justified_pe(roe: float, g: float, r: float) -> float:
    """``PE = (1 − g/ROE) / (r − g)``（稳态）。

    >>> round(justified_pe(0.12, 0.08, 0.10), 1)
    16.7
    >>> round(justified_pe(0.30, 0.08, 0.10), 1)
    36.7
    """
    if roe <= 0:
        raise ValueError("ROE 必须为正——负 ROE 下本式无意义，应改用 RI/清算口径")
    if g >= r:
        raise ValueError(f"g={g:.2%} ≥ r={r:.2%}：戈登式失效，须改用 fade_pe 或三阶段 DDM")
    if g > roe:
        raise ValueError(f"g={g:.2%} > ROE={roe:.2%}：留存率 >100%，该增长无法内生维持")
    return (1 - g / roe) / (r - g)


def justified_pb(roe: float, g: float, r: float) -> float:
    """``PB = (ROE − g) / (r − g)``（§6.5.2 J 金融资本型同式）。

    与 justified_pe 同源：两边乘 ``EPS = ROE × BVPS`` 即得。

    >>> round(justified_pb(0.15, 0.05, 0.10), 2)
    2.0
    """
    if g >= r:
        raise ValueError(f"g={g:.2%} ≥ r={r:.2%}：戈登式失效")
    return (roe - g) / (r - g)


def implied_peg(pe: float, g: float) -> float:
    """由合理 PE 反算出的 PEG——**这是输出，不是输入**（OI-023 的全部要点）。

    >>> round(implied_peg(22.0, 0.12), 2)
    1.83
    """
    if g <= 0:
        raise ValueError("g 必须为正才能算 PEG")
    return pe / (g * 100)


def fade_pe(roe0: float, g0: float, r: float,
            n1: int = 3, n2: int = 5,
            g_terminal: float = TERMINAL_GROWTH_DEFAULT,
            roe_terminal: float | None = None) -> float:
    """三段式合理 PE：高增长 n1 年 → 线性衰减 n2 年 → 永续。

    对**每股收益为 1** 的公司逐年推：留存 ``b_t = g_t / ROE_t``、派息 ``1 − b_t``，
    折现全部派息，终值用稳态戈登。ROE 同步由 ``roe0`` 线性回落到 ``roe_terminal``
    （缺省取 ``max(r + 2pp, roe0 的一半)``——竞争压低超额 ROE，但不至于跌破资本成本）。

    **为什么必须有这一段**：单阶段戈登在 ``g`` 接近 ``r`` 时分母趋零，PE 会爆掉；
    直接拿当前增速当永续增长是本路径最容易犯的错（§6.8 美团判例）。

    >>> pe = fade_pe(0.25, 0.15, 0.10)
    >>> 15 < pe < 60
    True
    """
    if g_terminal >= r:
        raise ValueError(f"g∞={g_terminal:.2%} ≥ r={r:.2%}：终值发散")
    if roe_terminal is None:
        roe_terminal = max(r + 0.02, roe0 / 2)
    if roe_terminal <= g_terminal:
        raise ValueError("终值 ROE 必须高于终值增长，否则留存率 >100%")

    eps, value = 1.0, 0.0
    for t in range(1, n1 + n2 + 1):
        if t <= n1:
            g_t, roe_t = g0, roe0
        else:                                   # 线性衰减段
            step = (t - n1) / n2
            g_t = g0 + (g_terminal - g0) * step
            roe_t = roe0 + (roe_terminal - roe0) * step
        eps *= (1 + g_t)
        payout = max(0.0, 1 - g_t / roe_t)
        value += eps * payout / (1 + r) ** t

    eps_terminal = eps * (1 + g_terminal)
    payout_terminal = 1 - g_terminal / roe_terminal
    terminal = eps_terminal * payout_terminal / (r - g_terminal)
    value += terminal / (1 + r) ** (n1 + n2)
    return value                                # EPS0 = 1，故现值即 PE


def print_grid(r: float) -> None:
    """OI-023 要的那张梯度——**由公式生成，不是人排的档位表**。"""
    roes = [0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.35]
    gs = [0.05, 0.08, 0.10, 0.12, 0.15]
    print(f"合理 PE（稳态戈登，r = {r:.1%}）——行 ROE × 列 g")
    print(f"  {'ROE\\g':>7}" + "".join(f"{g:>10.0%}" for g in gs))
    for roe in roes:
        cells = []
        for g in gs:
            try:
                cells.append(f"{justified_pe(roe, g, r):>10.1f}")
            except ValueError:
                cells.append(f"{'—':>10}")
        print(f"  {roe:>7.0%}" + "".join(cells))

    print(f"\n**隐含 PEG（= 合理 PE ÷ g×100）**——这是输出。OI-023 实测全池 84/148 家取 1.0，"
          f"而按经济关系，PEG 在任何一列都随 ROE 单调上升：")
    print(f"  {'ROE\\g':>7}" + "".join(f"{g:>10.0%}" for g in gs))
    for roe in roes:
        cells = []
        for g in gs:
            try:
                cells.append(f"{implied_peg(justified_pe(roe, g, r), g):>10.2f}")
            except ValueError:
                cells.append(f"{'—':>10}")
        print(f"  {roe:>7.0%}" + "".join(cells))

    print(f"\n三段式合理 PE（fade：高增长 3 年 → 衰减 5 年 → 永续 {TERMINAL_GROWTH_DEFAULT:.0%}，r = {r:.1%}）")
    print(f"  {'ROE\\g0':>7}" + "".join(f"{g:>10.0%}" for g in gs))
    for roe in roes:
        cells = []
        for g in gs:
            try:
                cells.append(f"{fade_pe(roe, g, r):>10.1f}")
            except ValueError:
                cells.append(f"{'—':>10}")
        print(f"  {roe:>7.0%}" + "".join(cells))
    print("\n对照两表即可看出**为什么不能直接用单阶段戈登**：g 接近 r 时稳态式的分母趋零、PE 爆掉，"
          "而三段式因增长会衰减、ROE 会回落，给出的是可辩护的量级。")

    print(f"\n**三段式的隐含 PEG**——OI-023 要的那条梯度，由公式生成而非人排档位（r = {r:.1%}）：")
    print(f"  {'ROE\\g0':>7}" + "".join(f"{g:>10.0%}" for g in gs))
    for roe in roes:
        cells = []
        for g in gs:
            try:
                cells.append(f"{implied_peg(fade_pe(roe, g, r), g):>10.2f}")
            except ValueError:
                cells.append(f"{'—':>10}")
        print(f"  {roe:>7.0%}" + "".join(cells))
    print("  读法：在 g 固定的任一列上，PEG 随 ROE **单调上升**——这正是 §6.5.2 声称、而全池实测不存在的那条梯度。"
          "\n  且三段式给出的量级（多数落在 0.9~1.5）与全池现用的 1.0~1.25 是同一区间，"
          "说明**现用取值的水平不离谱，缺的是随 ROE 的分辨力**。")


def self_test() -> int:
    import doctest
    failures, tested = doctest.testmod(verbose=False).failed, 0
    checks = [
        ("用户判例 A：ROE12%/g8%/r10% → PE≈16.7", abs(justified_pe(0.12, 0.08, 0.10) - 16.667) < 0.01),
        ("用户判例 B：ROE30%/g8%/r10% → PE≈36.7", abs(justified_pe(0.30, 0.08, 0.10) - 36.667) < 0.01),
        ("PEG 随 ROE 单调上升（g=10%,r=11%）",
         all(implied_peg(justified_pe(a, 0.10, 0.11), 0.10) < implied_peg(justified_pe(b, 0.10, 0.11), 0.10)
             for a, b in zip([0.12, 0.15, 0.20, 0.25], [0.15, 0.20, 0.25, 0.30]))),
        ("justified_pb 与 justified_pe 同源：PB = PE × ROE",
         abs(justified_pb(0.20, 0.06, 0.10) - justified_pe(0.20, 0.06, 0.10) * 0.20) < 1e-9),
        ("g ≥ r 必须报错而不是给个数",
         _raises(lambda: justified_pe(0.20, 0.11, 0.10))),
        ("g > ROE（留存率>100%）必须报错",
         _raises(lambda: justified_pe(0.10, 0.12, 0.15))),
        ("fade 在 g0 > r 时仍可算（衰减段兜住）", fade_pe(0.25, 0.20, 0.10) > 0),
    ]
    for label, ok in checks:
        tested += 1
        print(f"  {'✅' if ok else '❌'} {label}")
        failures += 0 if ok else 1
    print(f"自检 {tested} 项，失败 {failures} 项")
    return 1 if failures else 0


def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="合理倍数：PE/PB 由 ROE·g·r 推出，PEG 作为输出（OI-023）")
    parser.add_argument("--roe", type=float)
    parser.add_argument("--g", type=float, help="增长率（稳态用，或 fade 的起始增长）")
    parser.add_argument("--r", type=float, default=0.10, help="要求回报率，缺省 10%%")
    parser.add_argument("--grid", action="store_true", help="打印 ROE × g 网格")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.grid or args.roe is None or args.g is None:
        print_grid(args.r)
        return 0

    pe = justified_pe(args.roe, args.g, args.r)
    print(f"ROE {args.roe:.1%}｜g {args.g:.1%}｜r {args.r:.1%}")
    print(f"  稳态合理 PE   {pe:.1f}｜隐含 PEG {implied_peg(pe, args.g):.2f}｜合理 PB {justified_pb(args.roe, args.g, args.r):.2f}")
    print(f"  三段式合理 PE {fade_pe(args.roe, args.g, args.r):.1f}"
          f"｜隐含 PEG {implied_peg(fade_pe(args.roe, args.g, args.r), args.g):.2f}"
          f"（高增长 3 年 → 衰减 5 年 → 永续 {TERMINAL_GROWTH_DEFAULT:.0%}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
