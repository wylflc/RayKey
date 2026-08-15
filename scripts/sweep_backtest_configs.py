"""多配置 × 多起点的回测扫描器，并按 §12.1 的读数纪律出对照表。

**为什么进仓库**：此前每一轮参数实验都在临时目录里重写一份扫描器，
于是「§9.7.1.2 的那条完整命令」在每轮里各抄一遍，抄漏一个开关就整轮作废
（`docs/000_Ashare_workflow.md` §12.1 记着两次前车之鉴：`--max-corr` 缺省 0、`--lot-size` 缺省 0）。
本脚本把**那条完整命令固化成 `BASE`**，配置文件只写「相对基准改了什么」。

配置文件每行： `标签|额外参数`，**额外参数只写「相对基准改了什么」**——
逐日状态、宇宙面板、三条线都已在 `BASE` 里给全，不必也不该在每行重抄
（重抄一次就多一次抄漏的机会，而抄漏 `--universe-file` 会静默退回今日 261 池、读数含选样前视）。
**标签为 `BASE` 的那一行是对照臂**（额外参数留空即可），Δ 一律相对它算。
同名开关重复给时以后者为准，故要改哪条就在该行写哪条。

    BASE|
    D110|--entry-mode both --dev-buy-max 1.10
    U3|--universe-file data/processed/pit_attention/panel_moat_bank_v3.csv

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
import os
import re
import shlex
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data/processed/backtest"

# §9.7.1.2 的基准臂，逐字对应。**改这里之前先改工作流正文，不得单方面漂移。**
#
# **宇宙 = V4 面板**（`panel_moat_bank_v4.csv`，211 只，已按 `exit_log.csv` 的 X1/X3 退出与
# 对称重入逐档切换在册状态；见 `docs/Ashare_backtest_log.md` §12.53~§12.54）。
# **三条线与 §9.7.1 的生产线同值**（v2.98 起，用户 2026-08-14 指定买 1.00 / 减 2.50 / 换仓改善 0.15；
# 上一版基准臂为了与 V3 可比而单解过一套对齐线 1.5884/1.1044/0.1503，现已废止，不再维护两组数）。
# **`--position-cap 0.15` 于 v3.01 并入**（用户 2026-08-15 指令）——缺省是 0 即无上限，
# 漏给会静默退回「单票可占八成仓位」的旧口径（实测基准 79% 的交易日单票 >30%、峰值 84.5%，OI-057）。
# 基准读数见 `docs/000_Ashare_workflow.md` §9.7.1.2 节末的「v3.01 基准读数」——**改这里就要改那里**。
# **换估值口径或换宇宙做 A/B 时仍须把三条线一起重解到同一合格面**（§12.30，align_buy_line.py）；
# 改交易参数本身不需要对齐。
BASE = (
    "--strategy trend --trend-tranche --x 1.0 --trend-ma 20 60 "
    "--corr-window 252 --scan-depth 40 --max-positions 999 --max-corr 0.85 "
    "--swap --swap-partial --sell-trend-ma 20 "
    "--lot-size 100 --lot-ratio-cooldown --exec-delay 1 --exec-price close "
    "--fee-preset user --no-artifacts "
    "--width 0.0 --sell-line 2.50 --swap-margin 0.15 --position-cap 0.15 "
    "--daily-states data/processed/a_share_daily_states_adopted.csv "
    "--universe-file data/processed/pit_attention/panel_moat_bank_v4.csv"
)
# 每半年一个起点，2009-11 ~ 2020-11 共 23 个（§12.39.2 以来的标准起点集）。
DEFAULT_STARTS = [f"{y}-{m}-01" for y in range(2009, 2021) for m in ("05", "11")][1:]

FIELDS = ("年化", "最大回撤", "Sharpe", "Calmar", "平均仓位", "年均换手",
          "滚动3年年化中位", "滚动3年回撤中位", "滚动3年Calmar中位", "滚动3年为负的窗口占比",
          "滚动5年年化中位", "滚动5年回撤中位", "滚动5年为负的窗口占比",
          "逐年收益中位", "逐年为正比例", "逐年最差", "完整自然年数")
# 用户 2026-08-15：**判优劣不再用「某年至今的年化」**——那条读数被单个起点决定，
# 一次崩盘落在窗口内外就能翻转结论。改用滚动 3 年 / 滚动 5 年 / 逐年三条，Δ 以滚动 3 年为首。
# 三条口径**不可互换**：基准 2009-11 起点全期年化 12.28%，但滚动 5 年年化中位 18.01%
# ——滚动窗口不含「从起点一路跌下去」那些段，天然高于全期 CAGR。
DELTA_KEYS = ("滚动3年年化中位", "滚动5年年化中位", "逐年收益中位")


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
    print(f"{title}（{len(starts)} 个起点，对照＝BASE；Δ 按滚动3年排序）")
    print(f"{'配置':<14}{'Δ滚3':>8}{'符号':>7}{'Δ滚5':>8}{'符号':>7}{'Δ逐年':>8}{'符号':>7}"
          f"{'滚3年化':>8}{'滚5年化':>8}{'逐年中位':>9}{'逐年正':>7}"
          f"{'滚3回撤':>8}{'换手':>6}{'仓位':>5}")
    rows = []
    for label in order:
        arm = arms[label]
        common = [s for s in starts if s in arm and s in base]
        if not common:
            continue
        # 三条口径各算各的 Δ 与符号数。**符号数不是「哪条口径」的性质，是起点敏感性的性质**
        # ——中位为正而符号 12/23 说明效应由少数起点扛着，与用哪条读数无关（§12.1 第①层）。
        dz = {k: [arm[s][k] - base[s][k] for s in common] for k in DELTA_KEYS}
        # `arm`/`common` 是循环变量，闭包会晚绑定到最后一轮——必须用默认参数当场固定，
        # 否则每一行打印出来的都是最后一条臂的读数（Δ 列因为是即时算的，反而看不出错）。
        med = lambda k, _a=arm, _c=common: statistics.median(_a[s][k] for s in _c)
        rows.append((statistics.median(dz[DELTA_KEYS[0]]), label, dz, len(common), med))
    for _sort, label, dz, n, med in sorted(rows, key=lambda t: -t[0]):
        cells = ""
        for k in DELTA_KEYS:
            d = dz[k]
            cells += f"{statistics.median(d) * 100:>+8.2f}{f'{sum(1 for v in d if v > 0)}/{n}':>7}"
        print(f"{label:<14}{cells}"
              f"{med('滚动3年年化中位') * 100:>8.2f}{med('滚动5年年化中位') * 100:>8.2f}"
              f"{med('逐年收益中位') * 100:>9.2f}{med('逐年为正比例') * 100:>7.0f}"
              f"{med('滚动3年回撤中位') * 100:>8.1f}{med('年均换手'):>6.2f}"
              f"{med('平均仓位') * 100:>5.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", type=Path, help="配置文件；只出表时可省略")
    ap.add_argument("--out", type=Path, required=True, help="读数落点（每行一次运行）")
    ap.add_argument("--starts", default="", help="逗号分隔的起点；缺省是 23 个标准起点")
    ap.add_argument("--workers", type=int, default=8)
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
