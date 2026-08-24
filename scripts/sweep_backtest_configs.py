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
    python3 scripts/sweep_backtest_configs.py <配置文件> --out out.txt          # 缺省 23 个起点
    python3 scripts/sweep_backtest_configs.py <配置文件> --out out.txt --starts 2009-11-01,2013-11-01
    python3 scripts/sweep_backtest_configs.py --report out.txt                 # 只出表，不重跑

**一律带 `--no-artifacts`**：扫描只看 summary，逐笔/逐日/逐期三份产物是纯浪费——
一轮 253 次运行会落 759 个文件约 5 GB，且目录堆大后回测本身会变慢（§12.41）。
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
# 三条线与在册读数的历代纪元只查 `docs/Ashare_backtest_log.md`；现行三线与基准在册读数见工作流 §12.1。
# **`--position-cap 0.6`（v4.64，用户 2026-08-23 裁定）**：单票市值 ÷ 净资产 ≥ 60% 不再加仓、不足时补到 60%，只挡加仓不触发卖出
# （回测日志 §12.123：剂量 30~125% 里主读数到 50% 以下才现悬崖、风险改善 70% 以上几乎没有、Calmar/Sharpe 在 50~60% 达峰）。
# v4.04~v4.63 不给该开关（无上限，§12.75 用户 2026-08-17 裁定）。
# **规则与估值共适配**——同一规则在不同估值与宇宙上可反转，换估值口径须全规则重扫，
# 且**三条线一起重解到同一合格面**（§12.30，align_buy_line.py）。现行规则的逐项依据与读数见
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
    "--width 0.0657 --sell-line 2.4671 --swap-margin 0.1437 "
    # **止损线 = min(建仓日锚, 当日同周期均线)**（v4.25 用户裁定采纳，§12.88.2/§12.89：
    # 滚5 +0.59pp、16/23、逐年中性；均线上移不抬线，非 v2.56 那条双向滚动割肉）。
    # **建仓不设放弃规则**（v4.69 用户裁定取消，§12.126 追问检验：`skip` 与 `ma20_stop`
    # 23 起点配对差全读数 0.00、15 年仅触发 4~5 次）：照买，T 日收盘低于成交日 MA60 时锚退 MA20。
    "--stop-ma 60 --stop-line min_entry_current --entry-below-ma60 ma20_stop "
    # **OI-092 三处成文差异 23 起点 A/B（§12.126，2026-08-24）**：成文口径三臂主读数全负
    # （`skip_fill` −0.76、`--stop-basis signal` −0.42、`--residual-clear tranche` −0.44，合并 −1.41），
    # §9.3 成文改从实现（v4.68）；三开关缺省即现行，显式写出以防缺省漂移。
    "--stop-basis exec --residual-clear lot "
    "--position-cap 0.6 "
    "--addon-trend ma-only --swap-require-weak "
    "--daily-states data/processed/a_share_daily_states_adopted.csv "
    "--universe-file data/processed/pit_attention/panel_moat_bank_v6b.csv"
)
# 每半年一个起点，2009-11 ~ 2020-11 共 23 个（§12.39.2 以来的标准起点集）。
DEFAULT_STARTS = [f"{y}-{m}-01" for y in range(2009, 2021) for m in ("05", "11")][1:]

FIELDS = ("年化", "最大回撤", "Sharpe", "Calmar", "平均仓位", "年均换手",
          "滚动3年年化中位", "滚动3年回撤中位", "滚动3年Calmar中位", "滚动3年Sharpe中位", "滚动3年为负的窗口占比",
          "滚动5年年化中位", "滚动5年年化P25", "滚动5年年化最差", "滚动5年回撤中位", "滚动5年Calmar中位",
          "滚动5年Sharpe中位", "滚动5年为负的窗口占比", "滚动5年窗口数",
          "滚动10年年化中位", "滚动10年窗口数",
          "逐年收益中位", "逐年为正比例", "逐年最差", "完整自然年数")
# 用户 2026-08-17 重审：**判优劣不再用「某年至今的年化」**——那条读数被单个起点决定，
# 一次崩盘落在窗口内外就能翻转结论。缺省以更接近个人投资复利周期的滚动 5 年为收益主口径，
# 滚动 3 年只作较短状态诊断，逐年只描述单年分布；预计持有期改变时须在看结果前改主窗口。
# 三条口径**不可互换**，且**滚动口径只能比较不能当预期**——重叠窗口也不等于独立样本，
# 须另补互不重叠时期。见工作流 §12.1 与回测日志 §12.84。
# 用户 2026-08-23 矫正读数层级（回测日志 §12.121）：滚动窗口改**月末锚定**；决策读数只有四项——
# 主读数 = 滚 5 年 CAGR 中位的配对 Δ，坏情形 = 滚 5 年 CAGR P25 的配对 Δ，闸门 = 滚 5 年回撤中位
# 不得变深超过 3pp（同 §12.1 第 4 款的平台口径），否决 = 滚 5 年负收益窗口占比由 0 转正；
# 其余（滚 3、滚 10、逐年、全期）一律只描述。两层分位不要混：表里的「符号」是 23 个起点的配对差，
# P25／最差是**每个起点内** ~140 个月末窗口的分位。
DELTA_KEYS = ("滚动5年年化中位", "滚动5年年化P25", "滚动5年回撤中位")
AUX_DELTA_KEYS = ("滚动3年年化中位", "逐年收益中位", "年化")
PRIMARY_KEY = "滚动5年年化中位"
DRAWDOWN_GATE = 0.03      # 滚 5 年回撤中位配对 Δ 超过 +3pp（更深）即触发闸门标记


def run_one(job):
    label, extra, since = job
    tag = re.sub(r"[^A-Za-z0-9]", "", label + since)
    summary = OUT_DIR / f"summary_{tag}.csv"
    summary.unlink(missing_ok=True)
    cmd = ([sys.executable, str(ROOT / "scripts/backtest_valuation_strategy.py")]
           + shlex.split(BASE) + ["--since", since, "--label-suffix", "_" + tag]
           + shlex.split(extra))
    subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        rows = [r for r in csv.DictReader(summary.open(encoding="utf-8"))
                if r["策略"].startswith("trend_")]
    except (OSError, csv.Error, KeyError):
        return f"{label}|{since}|ERR"
    if not rows:
        return f"{label}|{since}|EMPTY"
    row = rows[-1]
    get = lambda k: float(row.get(k) or 0)
    return "|".join([label, since] + [f"{get(k):.6f}" for k in FIELDS])


def report(path: Path, title: str) -> None:
    """对照表。Δ 相对 `BASE` 臂，按 §12.1 同时给中位与符号数——单看中位会把掷硬币读成效应。"""
    arms: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    order: list[str] = []
    # 跑挂的运行以 `标签|起点|ERR`（或 `EMPTY`）落盘。**必须在这里数出来**——
    # 下面按字段数过滤会把它们丢掉，于是**整条臂全挂时它连一行都没有，表里完全不出现**，
    # 短臂告警（比较起点数）也发现不了。2026-08-15 实测撞到一次：`--stop-ma 120` 不在
    # argparse 的 choices 里，23 次运行全部退出，而对照表看上去一切正常。
    failed: dict[str, int] = collections.Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("|")
        if len(parts) == 3 and parts[2] in ("ERR", "EMPTY"):
            failed[parts[0]] += 1
        if len(parts) != 2 + len(FIELDS):
            continue
        label, since = parts[0], parts[1]
        if label not in order:
            order.append(label)
        arms[label][since] = dict(zip(FIELDS, map(float, parts[2:])))
    if failed:
        dead = [k for k in failed if k not in arms]
        print("⚠ 有运行跑挂了：" + "、".join(f"{k} {v} 次" for k, v in failed.items())
              + (f"\n  **其中 {'、'.join(dead)} 一行都没跑出来，下表里完全不会出现**"
                 "——先单跑一次看报错（多半是参数拼错或不在 choices 里），不要以为这些臂没测。"
                 if dead else ""), file=sys.stderr)
    if "BASE" not in arms:
        print("配置文件里没有 BASE 臂，无法算 Δ", file=sys.stderr)
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

    print(f"{title}（{len(starts)} 个起点，对照＝BASE；Δ 按滚 5 年中位排序；月末锚定滚动窗口）")
    print("【决策读数】Δ 为逐起点配对差中位（pp），符号 = 该读数为正的起点数；回撤 Δ 正 = 更深，"
          f"「更浅」= 回撤变浅的起点数；负窗↑ = 负收益窗口占比变大的起点数；闸门：回撤 Δ > +{DRAWDOWN_GATE*100:.0f}pp 或 负窗↑ 过半")
    print(f"{'配置':<14}{'Δ滚5中位':>9}{'符号':>7}{'Δ滚5P25':>9}{'符号':>7}{'Δ滚5回撤':>9}{'更浅':>7}{'负窗↑':>7}"
          f"{'滚5中位':>8}{'滚5P25':>8}{'滚5最差':>8}{'滚5回撤':>8}{'滚5Calmar':>10}{'滚5Sharpe':>10}{'负窗%':>6}{'换手':>6}{'仓位':>5}  闸门")
    for _sort, label, dz, n, med, neg_up in rows:
        d5, d25, dd = dz["滚动5年年化中位"], dz["滚动5年年化P25"], dz["滚动5年回撤中位"]
        flags = []
        if label != "BASE":
            if statistics.median(dd) > DRAWDOWN_GATE:
                flags.append("回撤变深")
            if neg_up > n / 2:
                flags.append("负窗转正")
        print(f"{label:<14}"
              f"{statistics.median(d5) * 100:>+9.2f}{f'{sum(1 for v in d5 if v > 0)}/{n}':>7}"
              f"{statistics.median(d25) * 100:>+9.2f}{f'{sum(1 for v in d25 if v > 0)}/{n}':>7}"
              f"{statistics.median(dd) * 100:>+9.2f}{f'{sum(1 for v in dd if v < 0)}/{n}':>7}{f'{neg_up}/{n}':>7}"
              f"{_fmt(med('滚动5年年化中位'))}{_fmt(med('滚动5年年化P25'))}{_fmt(med('滚动5年年化最差'))}"
              f"{_fmt(med('滚动5年回撤中位'), prec=1)}{_fmt(med('滚动5年Calmar中位'), 1, 10)}{_fmt(med('滚动5年Sharpe中位'), 1, 10)}"
              f"{_fmt(med('滚动5年为负的窗口占比'), 100, 6, 1)}{_fmt(med('年均换手'), 1, 6)}{_fmt(med('平均仓位'), 100, 5, 0)}"
              f"  {'、'.join(flags) if flags else ('—' if label != 'BASE' else '')}")

    print("【辅助读数】只描述不排序：滚 3 看短中期失效，滚 10 只在够长的起点上有值（空≠差），全期受起点单点决定")
    print(f"{'配置':<14}{'Δ滚3':>8}{'符号':>7}{'Δ逐年':>8}{'符号':>7}{'Δ年化':>8}{'符号':>7}"
          f"{'滚3年化':>8}{'滚3Calmar':>10}{'滚3Sharpe':>10}{'滚3回撤':>8}{'滚10年化':>9}{'起点数':>7}"
          f"{'年化':>7}{'最大回撤':>9}{'Calmar':>8}{'Sharpe':>8}{'逐年中位':>9}{'逐年正':>7}{'逐年最差':>9}")
    for _sort, label, dz, n, med, _neg in rows:
        cells = ""
        for k in AUX_DELTA_KEYS:
            d = dz[k]
            cells += f"{statistics.median(d) * 100:>+8.2f}{f'{sum(1 for v in d if v > 0)}/{n}':>7}"
        n10 = sum(1 for s in arms[label] if arms[label][s]["滚动10年窗口数"] > 0)
        print(f"{label:<14}{cells}"
              f"{_fmt(med('滚动3年年化中位'))}{_fmt(med('滚动3年Calmar中位'), 1, 10)}{_fmt(med('滚动3年Sharpe中位'), 1, 10)}"
              f"{_fmt(med('滚动3年回撤中位'), prec=1)}{_fmt(med('滚动10年年化中位'), 100, 9)}{n10:>7}"
              f"{_fmt(med('年化'), 100, 7)}{_fmt(med('最大回撤'), 100, 9, 1)}{_fmt(med('Calmar'), 1, 8)}{_fmt(med('Sharpe'), 1, 8)}"
              f"{_fmt(med('逐年收益中位'), 100, 9)}{_fmt(med('逐年为正比例'), 100, 7, 0)}{_fmt(med('逐年最差'), 100, 9, 1)}")


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
    ap.add_argument("--title", default="扫描结果")
    args = ap.parse_args()

    if not args.report:
        if not args.config:
            ap.error("要跑扫描就得给配置文件（只出表请加 --report）")
        starts = [s.strip() for s in args.starts.split(",") if s.strip()] or DEFAULT_STARTS
        jobs = []
        for line in args.config.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            label, extra = line.split("|", 1)
            jobs += [(label.strip(), extra, s) for s in starts]
        print(f"{len(jobs)} 次运行（{len(jobs) // len(starts)} 配置 × {len(starts)} 起点）"
              f"，{args.workers} 并发", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=args.workers) as pool, \
                args.out.open("w", encoding="utf-8") as fh:
            for done, result in enumerate(pool.map(run_one, jobs), 1):
                fh.write(result + "\n")
                fh.flush()
                if done % 25 == 0:
                    print(f"  {done}/{len(jobs)}", file=sys.stderr)
    report(args.out, args.title)


if __name__ == "__main__":
    main()
