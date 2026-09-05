"""清理两类**完全可重建**的派生产物，并把历次回测汇总归并成一张表。

**为什么需要它**：本仓库的实验产物增长极快——
`backtest_valuation_strategy.py` 每跑一次落四个文件，一轮参数扫描是几百次运行；
`build_historical_valuation_bands.py` 每个模型变体落一份 50~140MB 的逐日状态。
**两个区块，各自可单独跑**：

- `backtest`：`data/backtest/` 下的 `_equity`／`_trades`／`_periods` 三类删除；
  所有 `summary*.csv` 经 `write_ledger()` 归并进台账（多一列 `扫描标签`，并集列头、缺列留空，**一个数字都不丢**）：
  `计量版本` 等于现行引擎版本的行进 `scan_summaries.csv`，其余（含无该列的旧文件）进 `data/archive/scan_summaries_m1.csv`，
  随后按臂聚合重建 `scan_arms_index.csv`（§12.1 第 12 款数臂用）。实验脚本归档摘要**只走 `write_ledger()`**，不得自行写台账。
- `index`：只重建 `scan_arms_index.csv`。
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
    python3 scripts/clean_derived_artifacts.py index                # 只重建按臂索引
"""
import argparse
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_valuation_strategy import METRIC_VERSION  # noqa: E402  现行计量口径（§12.1 第 2 款）

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data/processed"
BACKTEST = ROOT / "data/backtest"
MERGED = BACKTEST / "scan_summaries.csv"
ARCHIVED_LEDGER = ROOT / "data/archive/scan_summaries_m1.csv"   # 旧计量口径行，只供数臂与复现
ARMS_INDEX = BACKTEST / "scan_arms_index.csv"
# 扫描标签 = [EX5:][<批次前缀><YYYYMMDD>_]<臂名><起点 YYYYMMDD>[ex5]；无起点日的标签整个作臂名
LABEL_RE = re.compile(r"^(?:EX5:)?(?:(?P<batch>[A-Za-z0-9]+?\d{8})_)?(?P<arm>.+?)(?P<start>\d{8})(?P<ex>ex5)?$")

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
    ROOT / "data/experiments" / "states",     # scripts/experimental/subset_daily_states.py
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


def _read_rows(path, tag=None):
    """读一份 CSV 为 (rows, columns)；给 `tag` 时每行补 `扫描标签`。"""
    rows, columns = [], []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if tag is not None:
                row["扫描标签"] = tag
            rows.append(row)
            for key in row:
                if key is not None and key not in columns:
                    columns.append(key)
    return rows, columns


def read_summaries(files):
    """读本次 summary*.csv，文件名去掉 `summary`／`.csv` 作 `扫描标签`；解析不了的文件跳过并报错。"""
    rows, columns = [], []
    for entry in sorted(files, key=lambda e: e.name):
        tag = entry.name[len("summary"):-len(".csv")].lstrip("_") or "-"
        try:
            got, cols = _read_rows(entry.path, tag)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            print(f"  跳过无法解析的 {entry.name}：{exc}", file=sys.stderr)
            continue
        rows += got
        columns += [c for c in cols if c not in columns]
    return rows, columns


def is_current(row) -> bool:
    """行的 `计量版本` 等于现行引擎版本才留在现行台账；空值是 m1 时代的旧文件。"""
    return (row.get("计量版本") or "") == METRIC_VERSION


class LedgerUpdate:
    """`merge_ledgers()` 的结果：两本台账各自的 (rows, columns, 新并入行数, 是否变化)。"""

    def __init__(self):
        self.current, self.current_columns, self.current_added, self.current_changed = [], [], 0, False
        self.archive, self.archive_columns, self.archive_added, self.archive_changed = [], [], 0, False
        self.arms = []


def merge_ledgers(files):
    """把本次 summary 并入两本台账（只算不写）。

    列头历代不同（滚动三年、手续费等是后加的），故取并集，缺列留空。**先读回两本台账再并入
    本次的 summary**：`scan_summaries.csv` 是 §12.1 第 12 款「已试臂数」的累计台账，直接按本次
    磁盘上剩余的 summary 覆写会把历次台账整表抹掉。同 `(扫描标签, 策略)` 后出现者胜；每行按
    `is_current()` 分流：现行口径进 `scan_summaries.csv`，其余进 `data/archive/scan_summaries_m1.csv`，
    已在现行台账里的旧口径行同样被搬走。
    """
    upd = LedgerUpdate()
    old_current, upd.current_columns = _read_rows(MERGED) if MERGED.exists() else ([], [])
    old_archive, upd.archive_columns = _read_rows(ARCHIVED_LEDGER) if ARCHIVED_LEDGER.exists() else ([], [])
    new_rows, new_columns = read_summaries(files)
    keyed = {}
    for source, rows in (("archive", old_archive), ("current", old_current), ("new", new_rows)):
        for row in rows:
            keyed[(row.get("扫描标签"), row.get("策略"))] = (source, row)
    for source, row in keyed.values():
        if is_current(row):
            upd.current.append(row)
            upd.current_added += source == "new"
            upd.current_changed |= source != "current"
        else:
            upd.archive.append(row)
            upd.archive_added += source == "new"
            upd.archive_changed |= source != "archive"
    upd.current_changed |= len(upd.current) != len(old_current)
    upd.archive_changed |= len(upd.archive) != len(old_archive)
    for rows, columns in ((upd.current, upd.current_columns), (upd.archive, upd.archive_columns)):
        for row in rows:
            columns += [c for c in row if c is not None and c not in columns]
    upd.current_columns = ["扫描标签"] + [c for c in upd.current_columns if c != "扫描标签"]
    upd.archive_columns = ["扫描标签"] + [c for c in upd.archive_columns if c != "扫描标签"]
    return upd


def _write_rows(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_ledger(files, apply=True):
    """台账的唯一写入口：归并本次 summary、按计量版本分流写两本台账、重建按臂索引。

    `apply=False` 只算不写。返回 `LedgerUpdate`（`arms` 为索引行，未写时为空）。
    """
    upd = merge_ledgers(files)
    if apply:
        if upd.current_changed or not MERGED.exists():
            _write_rows(MERGED, upd.current, upd.current_columns)
        if upd.archive_changed:
            _write_rows(ARCHIVED_LEDGER, upd.archive, upd.archive_columns)
        upd.arms = build_arms_index(apply=True)
    return upd


def arm_name(label: str):
    """把扫描标签拆成（臂名, 批次, 起点日, 是否剔除赢家遍）；拆不开的标签整个作臂名。"""
    m = LABEL_RE.match(label or "")
    if not m:
        return (label or "-", "", "", "")
    return (m.group("arm"), m.group("batch") or "", m.group("start"), "ex5" if m.group("ex") else "")


def build_arms_index(apply: bool):
    """按臂聚合现行台账与归档台账，写 `scan_arms_index.csv`（一臂一行）。"""
    arms = {}
    for src, ledger in (("current", MERGED), ("archive", ARCHIVED_LEDGER)):
        if not ledger.exists():
            continue
        with open(ledger, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                arm, batch, start, ex = arm_name(row.get("扫描标签", ""))
                rec = arms.setdefault(arm, {"批次": set(), "计量版本": set(), "起点": set(), "行数": 0,
                                            "剔除赢家行数": 0, "台账": set(), "策略示例": ""})
                rec["行数"] += 1
                rec["剔除赢家行数"] += 1 if ex else 0
                rec["台账"].add(src)
                if batch:
                    rec["批次"].add(batch)
                if start:
                    rec["起点"].add(start)
                rec["计量版本"].add(row.get("计量版本") or "m1")
                if not rec["策略示例"]:
                    rec["策略示例"] = re.sub(r"_?[A-Za-z0-9]*\d{8}(ex5)?$", "", row.get("策略") or "")
    fields = ["臂名", "台账", "计量版本", "批次", "起点数", "行数", "剔除赢家行数", "策略示例"]
    rows = [{"臂名": arm, "台账": "+".join(sorted(rec["台账"])), "计量版本": "+".join(sorted(rec["计量版本"])),
             "批次": ";".join(sorted(rec["批次"])), "起点数": len(rec["起点"]), "行数": rec["行数"],
             "剔除赢家行数": rec["剔除赢家行数"], "策略示例": rec["策略示例"]}
            for arm, rec in sorted(arms.items())]
    if apply:
        with open(ARMS_INDEX, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return rows


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
    ap.add_argument("block", nargs="?", choices=("backtest", "bands", "index", "all"), default="all")
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
            kept = sum(1 for _ in csv.DictReader(open(MERGED, encoding="utf-8"))) if MERGED.exists() else 0
            upd = write_ledger(summaries, apply=args.apply)
            print(f"  归并 → 现行台账 {len(upd.current):,} 行 × {len(upd.current_columns)} 列"
                  f"（原有 {kept:,} 行，本次并入 {upd.current_added:,} 行）；"
                  f"旧口径 {upd.archive_added:,} 行归 {ARCHIVED_LEDGER.relative_to(ROOT)}（共 {len(upd.archive):,} 行）")
            if args.apply:
                print(f"  已写 {MERGED.relative_to(ROOT)}（{human(MERGED.stat().st_size)}）"
                      + (f"、{ARCHIVED_LEDGER.relative_to(ROOT)}" if upd.archive_changed else ""))
                print(f"  已重建 {ARMS_INDEX.relative_to(ROOT)}：{len(upd.arms):,} 个臂")
            doomed += summaries
        freed += size(doomed)
        print(f"  待删 {len(doomed):,} 个 {human(size(doomed))}"
              + (f" → 已删 {remove(doomed, args.apply):,} 个" if args.apply else "  （未加 --apply）"))

    if args.block == "index":
        arms = build_arms_index(apply=True)
        print(f"[index] 已重建 {ARMS_INDEX.relative_to(ROOT)}：{len(arms):,} 个臂（{human(ARMS_INDEX.stat().st_size)}）")
        return

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
