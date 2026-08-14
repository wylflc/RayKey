"""多配置 × 多起点的回测扫描器，并按 §12.1 的读数纪律出对照表。

**为什么进仓库**：此前每一轮参数实验都在临时目录里重写一份扫描器，
于是「§9.7.1.2 的那条完整命令」在每轮里各抄一遍，抄漏一个开关就整轮作废
（`docs/000_Ashare_workflow.md` §12.1 记着两次前车之鉴：`--max-corr` 缺省 0、`--lot-size` 缺省 0）。
本脚本把**那条完整命令固化成 `BASE`**，配置文件只写「相对基准改了什么」。

配置文件每行： `标签|额外参数`
额外参数一般含 `--daily-states` 与 `--universe-file`（每条臂可用不同的逐日文件与面板）。
**标签为 `BASE` 的那一行是对照臂**，Δ 一律相对它算。

    BASE|--daily-states data/processed/a_share_daily_states_adopted.csv --universe-file … --width -0.5853
    D110|--daily-states … --universe-file … --width -0.5853 --entry-mode both --dev-buy-max 1.10

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

# §9.7.1.2 的完整命令，逐字对应。**改这里之前先改工作流正文，不得单方面漂移。**
#
# **对照臂的宇宙自 2026-08-14 起改为 V4 面板**（`panel_moat_bank_v4.csv`，211 只、已应用退出判定，
# 见 `docs/Ashare_backtest_log.md` §12.53~§12.54）。两步：①旧的 169 只面板因 OI-053 的接线错误漏掉
# 55 只已判入选公司 → 统一口径重判后补回，得 V3（211 只）；②V3 未接 `exit_log.csv` 的退出判定，
# 而 §9.7.2 第②条本就假定有退出 → 按 `notice` 可得日接回，得 V4。
# **对照臂须同时给** `--universe-file .../panel_moat_bank_v4.csv --width -0.5884 --sell-line 1.1044 --swap-margin 0.1503`。
# 基准读数：23 起点年化中位 **14.61%**、滚 3 年回撤中位 34.3%；2009-11 长跑年化 15.41%、最大回撤 49.8%。
BASE = (
    "--strategy trend --trend-tranche --trend-ma 20 60 --sell-line 1.10 "
    "--corr-window 252 --scan-depth 40 --max-positions 999 "
    "--swap --swap-partial --sell-trend-ma 20 "
    "--lot-size 100 --lot-ratio-cooldown --exec-delay 1 --exec-price close "
    "--x 1.0 --max-corr 0.85 --swap-margin 0.15 --fee-preset user --no-artifacts"
)
# 每半年一个起点，2009-11 ~ 2020-11 共 23 个（§12.39.2 以来的标准起点集）。
DEFAULT_STARTS = [f"{y}-{m}-01" for y in range(2009, 2021) for m in ("05", "11")][1:]

FIELDS = ("年化", "最大回撤", "Sharpe", "Calmar", "平均仓位", "年均换手",
          "滚动3年年化中位", "滚动3年回撤中位", "滚动3年Calmar中位", "滚动3年为负的窗口占比")


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
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("|")
        if len(parts) != 2 + len(FIELDS):
            continue
        label, since = parts[0], parts[1]
        if label not in order:
            order.append(label)
        arms[label][since] = dict(zip(FIELDS, map(float, parts[2:])))
    if "BASE" not in arms:
        print("配置文件里没有 BASE 臂，无法算 Δ", file=sys.stderr)
        return
    base = arms["BASE"]
    starts = sorted({s for a in arms.values() for s in a})
    print(f"{title}（{len(starts)} 个起点，对照＝BASE）")
    print(f"{'配置':<14}{'Δ年化中位':>10}{'符号':>8}{'年化':>8}{'Sharpe':>8}"
          f"{'滚3回撤':>9}{'滚3Calmar':>10}{'换手':>7}{'仓位':>6}")
    rows = []
    for label in order:
        arm = arms[label]
        common = [s for s in starts if s in arm and s in base]
        if not common:
            continue
        deltas = [arm[s]["年化"] - base[s]["年化"] for s in common]
        # `arm`/`common` 是循环变量，闭包会晚绑定到最后一轮——必须用默认参数当场固定，
        # 否则每一行打印出来的都是最后一条臂的读数（Δ 列因为是即时算的，反而看不出错）。
        med = lambda k, _a=arm, _c=common: statistics.median(_a[s][k] for s in _c)
        rows.append((statistics.median(deltas), label, sum(1 for d in deltas if d > 0),
                     len(common), med))
    for delta, label, pos, n, med in sorted(rows, reverse=True):
        print(f"{label:<14}{delta * 100:>+10.2f}{f'{pos}/{n}':>8}{med('年化') * 100:>8.2f}"
              f"{med('Sharpe'):>8.2f}{med('滚动3年回撤中位') * 100:>9.1f}"
              f"{med('滚动3年Calmar中位'):>10.2f}{med('年均换手'):>7.2f}{med('平均仓位') * 100:>6.0f}")


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
