"""清理两类**完全可重建**的派生产物，并把历次回测汇总归并成一张表。

**为什么需要它**：本仓库的实验产物增长极快——
`backtest_valuation_strategy.py` 每跑一次落四个文件，一轮参数扫描是几百次运行；
`build_historical_valuation_bands.py` 每个模型变体落一份 50~140MB 的逐日状态。
**两个区块，各自可单独跑**：

- `backtest`：`data/processed/backtest/` 下的 `_equity`／`_trades`／`_periods` 三类删除；
  所有 `summary*.csv` 归并成 `scan_summaries.csv`（多一列 `扫描标签`，并集列头、缺列留空，**一个数字都不丢**）。
- `bands`：`data/processed/` 下一次性估值带变体（`vd_*`／`vb_*`／`hd_*`／`hb_*`／`hist_daily_*`／
  `a_share_daily_g*`、退役的 `a_share_historical_valuation_*`、`dcf_*`／`roiccond*`／`roicmed_*` 实验臂、
  `diag_*` 诊断集）删除，并清空实验缓存目录 `metric_states/`、`experiments/states/` 与 `exp_b_market_cache.npz`。

**保留清单是硬编码的白名单**（`KEEP`），凡在其中者任何模式都不碰——
它们是生产口径的落点与脚本缺省值，删了会让 §9.3.1.2 与日常扫描直接失效。

缺省只报告，`--apply` 才动手。重建命令见 `docs/000_Ashare_workflow.md` §6.7 与 §9.3.1.2。

用法：
    python3 scripts/clean_derived_artifacts.py                      # 报告两个区块
    python3 scripts/clean_derived_artifacts.py --apply              # 两个区块都清
    python3 scripts/clean_derived_artifacts.py backtest --apply     # 只清回测产物
    python3 scripts/clean_derived_artifacts.py bands --apply        # 只清估值带变体
"""
import argparse
import csv
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data/processed"
BACKTEST = PROCESSED / "backtest"
MERGED = BACKTEST / "scan_summaries.csv"

BULK_SUFFIXES = ("_equity.csv", "_trades.csv", "_periods.csv")
# `summary.csv` 是每次运行的落点，留给下一次覆盖；`scan_summaries.csv` 是归并结果。
BACKTEST_KEEP = {"summary.csv", MERGED.name}

# 一次性估值带变体。**注意 `vd_`/`vb_` 前缀下有生产文件，靠 KEEP 白名单挡住。**
BANDS_PATTERN = re.compile(
    r"^(vd_|vb_|hd_|hb_|hist_daily_|hist_bands_|a_share_daily_g)"
    r"|^a_share_historical_valuation_(daily|bands)(_(pit|pit116|pit91|261L2))?\.csv$"
    # §12.66~§12.69 的估值引擎实验臂（dcf / roiccond* / roicmed），每臂三份 1.7~2 GB
    r"|^(dcf|ame|roiccond[0-9a-z]*|roicmed)_(bands|daily_raw|states)\.csv$"
    # notebooks/valuation_band_vs_price.ipynb 的诊断集（notebook 第二格一条命令重建）
    r"|^diag_(daily_states|bands)\.csv$"
)
# 生产口径的落点（§6.7 第 2/3 步产物、§9.3.1.2 回测输入）——**任何模式都不得删**。
KEEP = {
    "roic_bands.csv",
    "roic_daily_raw.csv",
    "a_share_daily_states_adopted.csv",
}
# 实验缓存目录/文件：整目录可由对应脚本一条命令重建（scripts/experimental/README.md）。
EXPERIMENT_DIRS = (
    PROCESSED / "metric_states",              # scripts/archive/build_metric_states.py
    PROCESSED / "experiments" / "states",     # scripts/experimental/subset_daily_states.py
)
EXPERIMENT_FILES = (
    ROOT / "data/interim/exp_b_market_cache.npz",   # scripts/experimental/vp_signal_lab.py 自动重建
)


def human(n: int) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else (f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB")


def collect_backtest():
    bulk, summaries = [], []
    if not BACKTEST.is_dir():
        return bulk, summaries
    for entry in os.scandir(BACKTEST):
        if not entry.is_file() or entry.name in BACKTEST_KEEP:
            continue
        if entry.name.endswith(BULK_SUFFIXES):
            bulk.append(entry)
        elif entry.name.startswith("summary") and entry.name.endswith(".csv"):
            summaries.append(entry)
    return bulk, summaries


def collect_bands():
    return [e for e in os.scandir(PROCESSED)
            if e.is_file() and e.name not in KEEP and BANDS_PATTERN.match(e.name)]


def collect_experiments():
    found = []
    for d in EXPERIMENT_DIRS:
        if d.is_dir():
            found += [e for e in os.scandir(d) if e.is_file()]
    for f in EXPERIMENT_FILES:
        if f.is_file():
            found += [e for e in os.scandir(f.parent) if e.is_file() and e.name == f.name]
    return found


def merge_summaries(files):
    """列头历代不同（滚动三年、手续费等是后加的），故取并集，缺列留空。"""
    rows, columns = [], []
    for entry in sorted(files, key=lambda e: e.name):
        tag = entry.name[len("summary"):-len(".csv")].lstrip("_") or "-"
        try:
            with open(entry.path, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    row["扫描标签"] = tag
                    rows.append(row)
                    for key in row:
                        if key is not None and key not in columns:
                            columns.append(key)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            print(f"  跳过无法解析的 {entry.name}：{exc}", file=sys.stderr)
    return rows, ["扫描标签"] + [c for c in columns if c != "扫描标签"]


def remove(entries, apply: bool) -> int:
    if not apply:
        return 0
    removed = 0
    for entry in entries:
        try:
            os.remove(entry.path)
            removed += 1
        except OSError as exc:
            print(f"  删不掉 {entry.name}：{exc}", file=sys.stderr)
    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("block", nargs="?", choices=("backtest", "bands", "all"), default="all")
    ap.add_argument("--apply", action="store_true", help="真的写与删；缺省只报告")
    ap.add_argument("--keep-summaries", action="store_true", help="不归并也不删 summary*.csv")
    args = ap.parse_args()
    size = lambda es: sum(e.stat().st_size for e in es)
    freed = 0

    if args.block in ("backtest", "all"):
        bulk, summaries = collect_backtest()
        print(f"[backtest] {BACKTEST.relative_to(ROOT)}")
        print(f"  逐日净值/逐笔成交/逐期收益（可重建） {len(bulk):>8,} 个 {human(size(bulk)):>10}")
        print(f"  历次扫描汇总                     {len(summaries):>8,} 个 {human(size(summaries)):>10}")
        doomed = list(bulk)
        if summaries and not args.keep_summaries:
            rows, columns = merge_summaries(summaries)
            print(f"  归并 → {len(rows):,} 行 × {len(columns)} 列")
            if args.apply:
                with open(MERGED, "w", encoding="utf-8", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
                print(f"  已写 {MERGED.relative_to(ROOT)}（{human(MERGED.stat().st_size)}）")
            doomed += summaries
        freed += size(doomed)
        print(f"  待删 {len(doomed):,} 个 {human(size(doomed))}"
              + (f" → 已删 {remove(doomed, args.apply):,} 个" if args.apply else "  （未加 --apply）"))

    if args.block in ("bands", "all"):
        doomed = collect_bands()
        freed += size(doomed)
        print(f"\n[bands] {PROCESSED.relative_to(ROOT)} 的一次性估值带变体")
        print(f"  待删 {len(doomed):,} 个 {human(size(doomed))}"
              + (f" → 已删 {remove(doomed, args.apply):,} 个" if args.apply else "  （未加 --apply）"))
        print(f"  白名单保留：{'、'.join(sorted(KEEP))}")
        cache = collect_experiments()
        freed += size(cache)
        print(f"  实验缓存（metric_states/、experiments/states/、exp_b_market_cache.npz）"
              f" 待删 {len(cache):,} 个 {human(size(cache))}"
              + (f" → 已删 {remove(cache, args.apply):,} 个" if args.apply else "  （未加 --apply）"))

    print(f"\n合计{'已释放' if args.apply else '可释放'} {human(freed)}")


if __name__ == "__main__":
    main()
