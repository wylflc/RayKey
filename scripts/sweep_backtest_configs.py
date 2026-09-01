"""多配置 × 多起点的回测扫描器，并按 §12.1 的读数纪律出对照表。

**为什么进仓库**：此前每一轮参数实验都在临时目录里重写一份扫描器，
于是「§9.3.1.2 的那条完整命令」在每轮里各抄一遍，抄漏一个开关就整轮作废
（引擎的 argparse 缺省值多为研究口径，漏一个开关读数就不是现行规则）。
本脚本把**那条完整命令固化成 `BASE`**，配置文件只写「相对基准改了什么」。

配置文件每行： `标签|额外参数`，**额外参数只写「相对基准改了什么」**——
逐日状态、宇宙面板、三条线都已在 `BASE` 里给全，不必也不该在每行重抄
（重抄一次就多一次抄漏的机会，而抄漏 `--universe-file` 会静默退回今日核心池、读数含选样前视）。
**标签为 `BASE` 的那一行是对照臂**（额外参数留空即可），Δ 一律相对它算。
同名开关重复给时以后者为准，故要改哪条就在该行写哪条。

    BASE|
    D110|--entry-mode both --dev-buy-max 1.10
    U6A|--universe-file data/processed/pit_attention/panel_moat_bank_v6a.csv

用法：
    python3 scripts/sweep_backtest_configs.py <配置文件> --out out.txt          # 缺省 14 个标准起点（路径 ≥10 年）
    python3 scripts/sweep_backtest_configs.py <配置文件> --out out.txt --starts 2009-11-01,2013-11-01
    python3 scripts/sweep_backtest_configs.py --report out.txt                 # 只出表，不重跑

**一律带 `--no-artifacts`**：扫描只看 summary，逐笔/逐日/逐期三份产物是纯浪费——
一轮 253 次运行会落 759 个文件约 5 GB，且目录堆大后回测本身会变慢（§12.41）。

**去赢家第二遍（§12.1 第 3 款的剔除集 A，缺省自动跑；剔除集 U 走 `ex_winner_symmetry.py`）**：第一遍跑完后，从 `BASE` 臂 2011-11-01 起点
（不在起点集时取最早起点）的 summary 读 `前五赢家`（全部闭合周期按代码汇总 `proceeds − invested`
的前五名），把同一组代码用 `--exclude-codes` 从**全部臂**统一剔除再跑一遍，结果行以 `EX5:` 前缀
落在同一个 --out 文件（另有一行 `#EX5|起点|代码` 记录赢家），`--report` 出两张表、第二张 Δ 对去赢家
`BASE` 配对。运行次数因此翻倍；`--no-ex-top5` 只用于复现旧读数或纯补跑。
"""
import argparse
import collections
import csv
import re
import shlex
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data/processed/backtest"

# §9.3.1.2 的现行基准臂，逐字对应。**改这里之前先改工作流正文，不得单方面漂移。**
#
# **估值 = ROIC 口径·分型锚＋增长腿**（`a_share_daily_states_adopted.csv`，重建见 §6.7：
#   `--roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak`）。
# **宇宙 = v6b 面板**（`panel_moat_bank_v6b.csv`，287 代码/现役 222）：§5.4 全口径逐年判定 + 全银行子册，
#   由 `verdicts_pit_moat_v6.csv` + `build_moat_panel.py` 确定性装配（§12.71，用户 2026-08-16 采纳）。
# 两条线与在册读数的历代纪元只查 `docs/Ashare_backtest_log.md`；现行两线与基准在册读数见工作流 §12.1。
# **`--position-cap 0.6`（v4.64，用户 2026-08-23 裁定）**：单票市值 ÷ 净资产 ≥ 60% 不再加仓、不足时补到 60%，只挡加仓不触发卖出
# （回测日志 §12.123：剂量 30~125% 里主读数到 50% 以下才现悬崖、风险改善 70% 以上几乎没有、Calmar/Sharpe 在 50~60% 达峰）。
# v4.04~v4.63 不给该开关（无上限，§12.75 用户 2026-08-17 裁定）。
# **规则与估值共适配**——同一规则在不同估值与宇宙上可反转，换估值口径须全规则重扫，
# 且**两条线一起重解到同一合格面**（§12.30，align_buy_line.py）。现行规则的逐项依据与读数见
# `docs/000_Ashare_workflow.md` §9.3.1/§9.3.1.2；**改这里就要先改那里的唯一标准落点**。
BASE = (
    # **一档 = 净资产 × 5.0%**（v4.06 用户裁定）。§12.91（v4.26 基准全量重扫 2~7%）：年化在
    # 4~5% 成台（4% vs 5% 噪声级），3% 起明确变差（滚5 −1.98pp、21/23 为负）；滚动回撤对档位
    # 单调（每 +1pp 档位 ≈ +0.5~1pp 滚3回撤），6%/7% 回撤变深且年化不涨。回撤敏感可取 4%。
    "--strategy trend --trend-tranche --x 5.0 --trend-ma 20 60 "
    "--corr-window 252 --scan-depth 40 --max-positions 999 --max-corr 0.70 "
    "--swap --swap-partial --sell-trend-ma 20 "
    "--lot-size 100 --lot-ratio-cooldown --exec-delay 1 --exec-price close "
    "--fee-preset user --no-artifacts "
    # **回测基础设置＝融资口径**（用户 2026-08-17 裁定，2026-08-22 改为不封顶）：本金 300 万、授信 = 净资产×66.6%（v4.66）
    # 不设金额上限、强平线 130%、融资年利率 3.5%。
    # **不给 `--margin-ratchet`**：该机制已于 2026-08-17 退役（§12.75），回测侧只作研究开关。
    # **§10.2 资金顺序（v4.40，OI-081 用户 2026-08-22 裁定）**：授信额度每日按净资产重定；当日卖出后负债超出额度的部分
    # 先用现金偿还、不可新增买入（`--credit-over-limit repay`）；换仓与买入都按「现金＋剩余授信」判资金是否够一档
    # （`--swap-trigger power`）；换仓卖出款同样先还、负债回到额度内才买（用户 2026-08-22 纠正，v4.41）。两者都是缺省，此处显式写出以防缺省漂移；v4.39 前旧口径 = `cash` + `keep`。
    # **v4.44（用户 2026-08-22 裁定）**：授信不设金额上限（`--credit-cap` 给极大数；比例 v4.66 起 66.6%）；
    # 同日采纳**涨幅减持** `--gain-sell 1.25 --gain-sell-mode gated`（收盘 ≥ 持仓均价×2.25 且收 < MA20 → 减一档，
    # 并优先作换仓卖出源；§12.110/§12.113）。生产落点 SEC93_GAIN_SELL（扫描器常量）＋ track_holdings_daily 提示。
    "--capital 3000000 --credit-ratio 0.666 --credit-cap 999999999999 "
    "--maintenance-ratio 1.30 --margin-rate 0.035 --swap-trigger power --credit-over-limit repay "
    "--gain-sell 1.25 --gain-sell-mode gated "
    # **v4.61 三线 = 连续判据纪元对齐解 0.9505/2.5263/0.1462**（用户 2026-08-23 裁定「三线按对齐解」，回测日志 §12.119；
    # v4.60 为 0.9503/2.5238/0.1462、v4.34 为 0.9434/2.5008/0.1451）
    # **v4.62 三线 = 季度当期化纪元对齐解 0.9343/2.4671/0.1437**（用户裁定「三线按对齐解」，回测日志 §12.120；v4.61 为 0.9505/2.5263/0.1462）
    # **v4.92 SPA（用户 2026-08-28 裁定采纳，回测日志 §12.136/§12.137）**：候选侧仍按 BASE 状态判买入线 0.9343；
    # 持仓侧（换仓来源／簇内升级／T+1 换仓确认）改读 max(BASE,B2) 状态（`--hold-states`）。
    # **v4.113 换仓边际 0.19**：不再随买入线缩放，按 0.01 一档剂量扫描定点；0.19 与 0.20 的取舍见回测日志 §12.152。
    # **不给 `--sell-line`**：估值减持在 v4.109 删除（OI-110），回测侧只作研究开关，给了才启用。
    "--width 0.0024 --swap-margin 0.19 "
    # **止损线 = min(建仓日锚, 当日同周期均线)**（v4.25 用户裁定采纳，§12.88.2/§12.89：
    # 滚5 +0.59pp、16/23、逐年中性；均线上移不抬线，非 v2.56 那条双向滚动割肉）。
    # **建仓不设放弃规则、锚恒取成交日 MA60**（v4.69/v4.70 用户裁定，§12.126 追问检验：
    # `skip`/`ma20_stop`/`ma60_stop` 三者两两 23 起点配对差全读数 0.00、触发情形 15 年仅 4~5 次）：
    # 照买，锚 = 成交日 MA60（缺失时退 MA20 兜底）。
    "--stop-ma 60 --stop-line min_entry_current --entry-below-ma60 ma60_stop "
    # **OI-092 三处成文差异 23 起点 A/B（§12.126，2026-08-24）**：成文口径三臂主读数全负
    # （`skip_fill` −0.76、`--stop-basis signal` −0.42、`--residual-clear tranche` −0.44，合并 −1.41），
    # §9.3 成文改从实现（v4.68）；三开关缺省即现行，显式写出以防缺省漂移。
    "--stop-basis exec --residual-clear lot "
    "--position-cap 0.6 "
    # 审计批 C（2026-08-24，用户裁定）：T+1 成交日无价该笔跳过（§9.1）、差别化股息税按 FIFO 结算、
    # 配股按交易所除权参考价折算并全额认购（事件库配股行）。`--fill-missing signal_close`／`--no-rights-events`／
    # 不给 `--dividend-tax` 为研究／复现口径。
    # **同日买卖对冲**（v4.104，§9.3.2 第 6 步）：同一信号日同一只股票的买入与卖出按较小者抵消，
    # 只执行净额、双边费税与股息税都不付；卖出与买入同日同价，故对冲精确。不给该开关即 v4.104 前旧口径。
    "--net-same-day "
    "--fill-missing skip --dividend-tax --swap-repeat skip "
    "--addon-trend ma-only --swap-require-weak "
    "--daily-states data/processed/a_share_daily_states_adopted.csv "
    "--hold-states data/processed/a_share_daily_states_hold.csv "
    "--universe-file data/processed/pit_attention/panel_moat_bank_v6b.csv"
)
# 用户 2026-09-02 裁定（§12.158/§12.160，v4.117）：标准起点集 = 路径 ≥10 年的全部半年档起点。
# 此前为 23 个（…~2020-11-01）；短路径 9 个起点的全期 CAGR 68%~100% 由 2020 年后构成、
# 对臂间 Δ 整块同向投票（1/9~3/9），属符号数假样本，砍掉。**该集随数据末端推进而扩**：
# 数据到 2026-11 时 2016-11-01 满 10 年，依次补入并按 §12 重登在册读数。
DEFAULT_STARTS = [f"{y}-{m}-01" for y in range(2009, 2017) for m in ("05", "11")][1:-1]

FIELDS = ("年化", "最大回撤", "Sharpe", "Calmar", "平均仓位", "年均换手",
          "持仓数中位", "单票权重中位", "单票权重P90", "单票权重最大", "前三权重中位", "单票超60%天数占比",
          "滚动3年年化中位", "滚动3年回撤中位", "滚动3年Calmar中位", "滚动3年Sharpe中位", "滚动3年为负的窗口占比",
          "滚动5年年化中位", "滚动5年年化P25", "滚动5年年化最差", "滚动5年回撤中位", "滚动5年Calmar中位",
          "滚动5年Sharpe中位", "滚动5年为负的窗口占比", "滚动5年窗口数", "互不重叠5年块中位",
          "滚动10年年化中位", "滚动10年窗口数",
          "逐年收益中位", "逐年为正比例", "逐年最差", "完整自然年数")
# 用户 2026-08-17 重审：**判优劣不再用「某年至今的年化」**——那条读数被单个起点决定，
# 一次崩盘落在窗口内外就能翻转结论。缺省以更接近个人投资复利周期的滚动 5 年为收益主口径，
# 滚动 3 年只作较短状态诊断，逐年只描述单年分布；预计持有期改变时须在看结果前改主窗口。
# 三条口径**不可互换**，且**滚动口径只能比较不能当预期**——重叠窗口也不等于独立样本，
# 须另补互不重叠时期。见工作流 §12.1 与回测日志 §12.84。
# 用户 2026-08-23 矫正读数层级（回测日志 §12.121）：滚动窗口改**月末锚定**；决策读数只有四项——
# 主读数 = 滚 5 年 CAGR 中位的配对 Δ，坏情形 = 滚 5 年 CAGR P25 的配对 Δ，闸门 = 滚 5 年回撤中位
# 不得变深超过 3pp（同 §12.1 第 5 款的平台口径），否决 = 滚 5 年负收益窗口占比由 0 转正；
# 其余（滚 3、滚 10、逐年、全期）一律只描述。两层分位不要混：表里的「符号」是标准起点集的配对差，
# P25／最差是**每个起点内**（64~142 个）月末窗口的分位。
# 用户 2026-09-01：**全期 CAGR 的配对 Δ 升为第五项决策读数（复利读数）**，四项 → 五项，
# 主读数与复利读数任一为负即不采纳。动机是滚动中位与逐年中位都不含跨窗口复利——逐年 −50%／+50%
# 交替的路径逐年中位为 0 而实际年化 −13.4%；全期 CAGR 是该起点到共同终点的真实复利结果。
# **两个长跑锚点（LONGRUN_STARTS）仍只描述**：它们是单起点水平值、常反号，比较一律走逐起点配对差。
# 用户 2026-09-01（OI-122，§12.157）：**臂间比较与「未来年化表现」的表述基准 = 复利读数**，
# 决策表按 Δ年化 排序；主读数仍为并列采纳门槛（5 年持有期的稳健性）。前沿预测力实测
# （benchmark_predictive_lab.py，6 臂 × 588 前沿细胞）：任何历史读数对未来 5 年的臂间 Δ 均无
# 正向传递（符号一致率 29~35%、MAE 全部跑输恒 Δ=0），故基准按「量的是否为年化本身」定，
# 不按预测力赛马定；Δ 读数与符号数是已过历史的描述与采纳门槛，不作未来 Δ 的点预测引用。
# 水平引用同理：滚动重叠中位被重叠×共享终点抬高约 25pp（§12.156 实测 65.46 vs 互不重叠 40.72），
# 未来年化的水平引用一律走全期口径（年化／互不重叠5年块中位／长跑锚点），滚动水平只描述窗口分布。
# **标准指标集**（§12.1 第 2 款）：每轮扫描在全样本与去赢家两个口径上各出一份，
# 每项报水平值、逐起点配对差中位与「变好的起点数」。`good` = +1 越大越好 / −1 越小越好。
# 长跑锚点是单起点，只报水平与差、不报符号数、不进第 4 款的「不劣」判定，故不在本表里。
STANDARD_SET = (
    ("滚5中位",   "滚动5年年化中位",     100, 8, 2, +1),
    ("滚5P25",    "滚动5年年化P25",      100, 8, 2, +1),
    ("滚5最差",   "滚动5年年化最差",     100, 8, 2, +1),
    ("滚5回撤",   "滚动5年回撤中位",     100, 8, 1, -1),
    ("滚5Calmar", "滚动5年Calmar中位",     1, 10, 2, +1),
    ("滚5Sharpe", "滚动5年Sharpe中位",     1, 10, 2, +1),
    ("负窗%",     "滚动5年为负的窗口占比", 100, 7, 1, -1),
    ("年化",      "年化",                100, 8, 2, +1),
    ("最大回撤",  "最大回撤",            100, 9, 1, -1),
    ("Calmar",    "Calmar",                1, 8, 2, +1),
    ("Sharpe",    "Sharpe",                1, 8, 2, +1),
    ("5年块中位", "互不重叠5年块中位",   100, 10, 2, +1),
    ("滚3中位",   "滚动3年年化中位",     100, 8, 2, +1),
    ("滚3回撤",   "滚动3年回撤中位",     100, 8, 1, -1),
    ("逐年中位",  "逐年收益中位",        100, 9, 2, +1),
    ("逐年最差",  "逐年最差",            100, 9, 1, +1),
    ("换手",      "年均换手",              1, 7, 2, -1),
    ("仓位",      "平均仓位",            100, 6, 0, -1),
)

DELTA_KEYS = ("滚动5年年化中位", "年化", "滚动5年年化P25", "滚动5年回撤中位")
EX5_PREFIX = "EX5:"              # 去赢家第二遍的结果行标签前缀
EX5_ANCHOR_START = "2011-11-01"  # 赢家取自 BASE 臂该起点（§12.132 起的定义）
EX5_FIELD = "前五赢家"           # 引擎 summary 里的赢家列（代码以 / 连接）
# **长跑年化**（§12.1 第 2 款）：单起点的全期 CAGR。两个锚点都报——最长路径与标准长跑常常反号，
# 只看一个会把「起点单点决定」读成效应（回测日志 §12.152：0.19 vs 0.20 在两锚上正好相反）。
LONGRUN_STARTS = ("2009-11-01", "2011-11-01")
AUX_DELTA_KEYS = ("滚动3年年化中位", "逐年收益中位")
PRIMARY_KEY = "年化"             # 排序键 = 复利读数（OI-122：臂间比较基准）
DRAWDOWN_GATE = 0.03      # 滚 5 年回撤中位配对 Δ 超过 +3pp（更深）即触发闸门标记


def summary_tag(label: str, since: str, exclude: str = "") -> str:
    return re.sub(r"[^A-Za-z0-9]", "", label + since + ("ex5" if exclude else ""))


def run_one(job):
    label, extra, since, exclude = job
    tag = summary_tag(label, since, exclude)
    out_label = (EX5_PREFIX + label) if exclude else label
    summary = OUT_DIR / f"summary_{tag}.csv"
    summary.unlink(missing_ok=True)
    cmd = ([sys.executable, str(ROOT / "scripts/backtest_valuation_strategy.py")]
           + shlex.split(BASE) + ["--since", since, "--label-suffix", "_" + tag]
           + shlex.split(extra) + (["--exclude-codes", exclude] if exclude else []))
    subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        rows = [r for r in csv.DictReader(summary.open(encoding="utf-8"))
                if r["策略"].startswith("trend_")]
    except (OSError, csv.Error, KeyError):
        return f"{out_label}|{since}|ERR"
    if not rows:
        return f"{out_label}|{since}|EMPTY"
    row = rows[-1]
    get = lambda k: float(row.get(k) or 0)
    return "|".join([out_label, since] + [f"{get(k):.6f}" for k in FIELDS])


def read_top5_winners(starts: list[str]) -> tuple[str, str]:
    """从第一遍 `BASE` 臂锚定起点的 summary 读前五赢家，返回 (起点, 逗号分隔代码)；读不到返回空代码。"""
    anchor = EX5_ANCHOR_START if EX5_ANCHOR_START in starts else starts[0]
    summary = OUT_DIR / f"summary_{summary_tag('BASE', anchor)}.csv"
    try:
        rows = [r for r in csv.DictReader(summary.open(encoding="utf-8"))
                if r["策略"].startswith("trend_")]
    except (OSError, csv.Error, KeyError):
        return anchor, ""
    if not rows or not rows[-1].get(EX5_FIELD):
        return anchor, ""
    return anchor, ",".join(c for c in rows[-1][EX5_FIELD].split("/") if c)


def report(path: Path, title: str) -> None:
    """对照表。Δ 相对 `BASE` 臂，按 §12.1 同时给中位与符号数——单看中位会把掷硬币读成效应。

    结果文件里 `EX5:` 前缀的行是去赢家第二遍，单独成表、Δ 对 `EX5:BASE` 配对。"""
    groups: dict[str, dict[str, dict[str, dict]]] = {"": collections.defaultdict(dict),
                                                       EX5_PREFIX: collections.defaultdict(dict)}
    orders: dict[str, list[str]] = {"": [], EX5_PREFIX: []}
    failed: dict[str, collections.Counter] = {"": collections.Counter(), EX5_PREFIX: collections.Counter()}
    ex5_note = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#EX5|"):
            _tag, anchor, codes = line.split("|", 2)
            ex5_note = f"剔除 BASE {anchor} 起点前五赢家 {codes.replace(',', '/')}"
            continue
        parts = line.split("|")
        grp = EX5_PREFIX if parts[0].startswith(EX5_PREFIX) else ""
        parts[0] = parts[0][len(grp):]
        if len(parts) == 3 and parts[2] in ("ERR", "EMPTY"):
            failed[grp][parts[0]] += 1
        if len(parts) != 2 + len(FIELDS):
            continue
        label, since = parts[0], parts[1]
        if label not in orders[grp]:
            orders[grp].append(label)
        groups[grp][label][since] = dict(zip(FIELDS, map(float, parts[2:])))
    _print_group(groups[""], orders[""], failed[""], title)
    if groups[EX5_PREFIX] or failed[EX5_PREFIX]:
        print()
        _print_group(groups[EX5_PREFIX], orders[EX5_PREFIX], failed[EX5_PREFIX],
                     f"{title}｜去赢家（剔除集 A：{ex5_note or '剔除 BASE 前五赢家'}；Δ 对同剔除集的 BASE 配对）"
                     f"。§12.1 第 4 款的「去赢家全面优秀」判定走剔除集 U，"
                     f"用 scripts/experimental/ex_winner_symmetry.py 另跑")


def _print_group(arms, order: list[str], failed, title: str) -> None:
    # 跑挂的运行以 `标签|起点|ERR`（或 `EMPTY`）落盘。**必须在这里数出来**——
    # 上面按字段数过滤会把它们丢掉，于是**整条臂全挂时它连一行都没有，表里完全不出现**，
    # 短臂告警（比较起点数）也发现不了。2026-08-15 实测撞到一次：`--stop-ma 120` 不在
    # argparse 的 choices 里，23 次运行全部退出，而对照表看上去一切正常。
    if failed:
        dead = [k for k in failed if k not in arms]
        print("⚠ 有运行跑挂了：" + "、".join(f"{k} {v} 次" for k, v in failed.items())
              + (f"\n  **其中 {'、'.join(dead)} 一行都没跑出来，下表里完全不会出现**"
                 "——先单跑一次看报错（多半是参数拼错或不在 choices 里），不要以为这些臂没测。"
                 if dead else ""), file=sys.stderr)
    if "BASE" not in arms:
        print(f"{title}：没有 BASE 臂，无法算 Δ", file=sys.stderr)
        return
    base = arms["BASE"]
    starts = sorted({s for a in arms.values() for s in a})
    # **跑挂的运行必须喊出来**：`run_one` 对失败返回 `ERR`/`EMPTY`，那种行的字段数对不上、
    # 在上面被静默跳过，于是该臂只剩下少数起点，表里只体现为「符号 3/15」这种不起眼的分母。
    # 2026-08-15 实测撞到一次：8 个并发各载一份 92MB 逐日状态，K33 臂有 8 次被打挂，
    # 差点把一个只有 15 个起点的读数当成 23 起点的结论。
    short = {label: len(arm) for label, arm in arms.items() if len(arm) < len(starts)}
    if short:
        print("⚠ 以下臂的起点不全（其余起点跑挂了，读数不可与满起点的臂直接比较）："
              + "、".join(f"{k} {v}/{len(starts)}" for k, v in short.items())
              + "\n  → 重跑这些臂，或降低 --workers（并发过高会因内存被打挂）", file=sys.stderr)
    def _med(vals):
        v = [x for x in vals if x == x]
        return statistics.median(v) if v else float("nan")

    def _fmt(x, scale=100.0, width=8, prec=2):
        return f"{'—':>{width}}" if x != x else f"{x * scale:>{width}.{prec}f}"

    rows = []
    for label in order:
        arm = arms[label]
        common = [s for s in starts if s in arm and s in base]
        if not common:
            continue
        # 各读数各算各的 Δ 与符号数。**符号数不是「哪条口径」的性质，是起点敏感性的性质**
        # ——中位为正而符号 12/23 说明效应由少数起点扛着，与用哪条读数无关（§12.1 第①层）。
        dz = {k: [arm[s][k] - base[s][k] for s in common] for k in DELTA_KEYS + AUX_DELTA_KEYS}
        # `arm`/`common` 是循环变量，闭包会晚绑定到最后一轮——必须用默认参数当场固定，
        # 否则每一行打印出来的都是最后一条臂的读数（Δ 列因为是即时算的，反而看不出错）。
        med = lambda k, _a=arm, _c=common: _med(_a[s][k] for s in _c)
        neg_up = sum(1 for s in common if arm[s]["滚动5年为负的窗口占比"] > base[s]["滚动5年为负的窗口占比"])
        rows.append((statistics.median(dz[PRIMARY_KEY]), label, dz, len(common), med, neg_up))
    rows.sort(key=lambda t: -t[0])

    print(f"{title}（{len(starts)} 个起点，对照＝BASE；Δ 按年化（复利读数）排序；月末锚定滚动窗口）")
    print("【决策读数】Δ 为逐起点配对差中位（pp），符号 = 该读数为正的起点数；回撤 Δ 正 = 更深，"
          f"「更浅」= 回撤变浅的起点数；负窗↑ = 负收益窗口占比变大的起点数；闸门：回撤 Δ > +{DRAWDOWN_GATE*100:.0f}pp 或 负窗↑ 过半")
    print(f"{'配置':<14}{'Δ滚5中位':>9}{'符号':>7}{'Δ年化':>8}{'符号':>7}{'Δ滚5P25':>9}{'符号':>7}{'Δ滚5回撤':>9}{'更浅':>7}{'负窗↑':>7}"
          f"{'滚5中位':>8}{'滚5P25':>8}{'滚5最差':>8}{'滚5回撤':>8}{'滚5Calmar':>10}{'滚5Sharpe':>10}{'负窗%':>6}{'换手':>6}{'仓位':>5}  闸门")
    for _sort, label, dz, n, med, neg_up in rows:
        d5, dcg, d25, dd = (dz["滚动5年年化中位"], dz["年化"],
                            dz["滚动5年年化P25"], dz["滚动5年回撤中位"])
        flags = []
        if label != "BASE":
            if statistics.median(dd) > DRAWDOWN_GATE:
                flags.append("回撤变深")
            if neg_up > n / 2:
                flags.append("负窗转正")
            if statistics.median(d5) < 0 or statistics.median(dcg) < 0:
                flags.append("主/复利为负")
        print(f"{label:<14}"
              f"{statistics.median(d5) * 100:>+9.2f}{f'{sum(1 for v in d5 if v > 0)}/{n}':>7}"
              f"{statistics.median(dcg) * 100:>+8.2f}{f'{sum(1 for v in dcg if v > 0)}/{n}':>7}"
              f"{statistics.median(d25) * 100:>+9.2f}{f'{sum(1 for v in d25 if v > 0)}/{n}':>7}"
              f"{statistics.median(dd) * 100:>+9.2f}{f'{sum(1 for v in dd if v < 0)}/{n}':>7}{f'{neg_up}/{n}':>7}"
              f"{_fmt(med('滚动5年年化中位'))}{_fmt(med('滚动5年年化P25'))}{_fmt(med('滚动5年年化最差'))}"
              f"{_fmt(med('滚动5年回撤中位'), prec=1)}{_fmt(med('滚动5年Calmar中位'), 1, 10)}{_fmt(med('滚动5年Sharpe中位'), 1, 10)}"
              f"{_fmt(med('滚动5年为负的窗口占比'), 100, 6, 1)}{_fmt(med('年均换手'), 1, 6)}{_fmt(med('平均仓位'), 100, 5, 0)}"
              f"  {'、'.join(flags) if flags else ('—' if label != 'BASE' else '')}")

    def longrun(label: str) -> str:
        """两个长跑锚点各自的全期 CAGR 与最大回撤；该锚点不在本轮起点集里就留空。"""
        out = ""
        for s in LONGRUN_STARTS:
            row = arms[label].get(s)
            out += (f"{row['年化'] * 100:>11.2f}{row['最大回撤'] * 100:>10.1f}"
                    if row else f"{'—':>11}{'—':>10}")
        return out

    print("【标准指标集】§12.1 第 2 款必报；除第 2 款五项决策读数外一律只描述不排序。"
          "长跑锚点是单起点水平值、常反号，不报符号数、不进第 4 款判定；滚 10 只在够长的起点上有值（空≠差）")
    print(f"{'配置':<14}"
          + "".join(f"{name:>{w}}" for name, _k, _s, w, _p, _g in STANDARD_SET)
          + f"{'长跑09CAGR':>11}{'长跑09MDD':>10}{'长跑11CAGR':>11}{'长跑11MDD':>10}{'滚10年化':>9}{'起点数':>7}")
    for _sort, label, _dz, _n, med, _neg in rows:
        n10 = sum(1 for s in arms[label] if arms[label][s]["滚动10年窗口数"] > 0)
        print(f"{label:<14}"
              + "".join(_fmt(med(k), s, w, pr) for _nm, k, s, w, pr, _g in STANDARD_SET)
              + longrun(label) + f"{_fmt(med('滚动10年年化中位'), 100, 9)}{n10:>7}")

    print("【标准指标集·配对差】Δ 为逐起点配对差中位，符号 = **该读数变好**的起点数"
          "（回撤／负窗／换手／仓位越小越好，其 Δ 为负即变好）；第 4 款「不劣」= Δ 方向不坏，或符号数不低于半数，"
          "换手与长跑锚点为参考项、不进该判定")
    challengers = [label for _s, label, _d, _n, _m, _ng in rows if label != "BASE"]
    if challengers:
        print(f"{'指标':<12}" + "".join(f"{c:>16}" for c in challengers))
        for name, k, scale, _w, prec, good in STANDARD_SET:
            cells = ""
            for c in challengers:
                common = [s for s in starts if s in arms[c] and s in base]
                d = [(arms[c][s][k] - base[s][k]) * scale for s in common]
                if not d:
                    cells += f"{'—':>16}"
                    continue
                better = sum(1 for v in d if v * good > 0)
                cells += f"{statistics.median(d):>+10.{max(prec, 1)}f}{f'{better}/{len(d)}':>6}"
            print(f"{name:<12}{cells}")

    # 【集中度】只描述不排序。分母一律是当日净资产，故融资下各列都可超过 100%；
    # 「仓位」＝持仓市值 ÷ 净资产（§12.1 第 2 款必报的那一列），与单票／前三权重同尺。
    print("【集中度】只描述不排序：分母＝当日净资产，融资下可超 100%；权重与超限天数只在有持仓的日子上统计")
    print(f"{'配置':<14}{'仓位':>7}{'持仓数':>7}{'单票中位':>9}{'单票P90':>9}{'单票最大':>9}{'前三中位':>9}{'超60%天':>9}")
    for _sort, label, _dz, _n, med, _neg in rows:
        print(f"{label:<14}{_fmt(med('平均仓位'), 100, 7, 1)}{_fmt(med('持仓数中位'), 1, 7, 1)}"
              f"{_fmt(med('单票权重中位'), 100, 9, 1)}{_fmt(med('单票权重P90'), 100, 9, 1)}"
              f"{_fmt(med('单票权重最大'), 100, 9, 1)}{_fmt(med('前三权重中位'), 100, 9, 1)}"
              f"{_fmt(med('单票超60%天数占比'), 100, 9, 1)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", type=Path, help="配置文件；只出表时可省略")
    ap.add_argument("--out", type=Path, required=True, help="读数落点（每行一次运行）")
    ap.add_argument("--starts", default="", help="逗号分隔的起点；缺省是 23 个标准起点")
    # **缺省 2**：单个回测进程实测峰值 1.25 GB（`/usr/bin/time -l`，2026-08-17），
    # 本机 8 GB 物理内存且 swap 为 0——缺省 8 并发 ≈ 10 GB，会把整机打到黑屏（已发生一次）。
    # 调高前先算：并发数 × 1.3 GB + 其它后台作业 必须 < 5 GB。见 CLAUDE.md「机器资源约束」。
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--report", action="store_true", help="不重跑，只对 --out 现有内容出表")
    ap.add_argument("--no-ex-top5", action="store_true",
                    help="不跑去赢家第二遍（§12.1 第 3 款要求每轮都跑；只在复现旧读数或纯补跑时给）")
    ap.add_argument("--title", default="扫描结果")
    args = ap.parse_args()

    if not args.report:
        if not args.config:
            ap.error("要跑扫描就得给配置文件（只出表请加 --report）")
        starts = [s.strip() for s in args.starts.split(",") if s.strip()] or DEFAULT_STARTS
        arms = []
        for line in args.config.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            label, extra = line.split("|", 1)
            arms.append((label.strip(), extra))
        if "BASE" not in {label for label, _e in arms}:
            ap.error("配置文件里没有 BASE 臂：Δ 与去赢家第二遍都以它为对照")

        def run_pass(jobs, fh, note: str) -> None:
            print(f"{note}：{len(jobs)} 次运行（{len(jobs) // len(starts)} 配置 × {len(starts)} 起点）"
                  f"，{args.workers} 并发", file=sys.stderr)
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for done, result in enumerate(pool.map(run_one, jobs), 1):
                    fh.write(result + "\n")
                    fh.flush()
                    if done % 25 == 0:
                        print(f"  {done}/{len(jobs)}", file=sys.stderr)

        with args.out.open("w", encoding="utf-8") as fh:
            run_pass([(label, extra, s, "") for label, extra in arms for s in starts], fh, "第一遍（全样本）")
            if not args.no_ex_top5:
                anchor, winners = read_top5_winners(starts)
                if not winners:
                    print(f"⚠ 读不到 BASE {anchor} 起点的 `{EX5_FIELD}`（该次运行跑挂或引擎过旧），"
                          "去赢家第二遍跳过——补跑后用 --report 出表仍只有第一张", file=sys.stderr)
                else:
                    fh.write(f"#EX5|{anchor}|{winners}\n")
                    fh.flush()
                    run_pass([(label, extra, s, winners) for label, extra in arms for s in starts], fh,
                             f"第二遍（统一剔除 BASE {anchor} 起点前五赢家 {winners}）")
    report(args.out, args.title)


if __name__ == "__main__":
    main()
