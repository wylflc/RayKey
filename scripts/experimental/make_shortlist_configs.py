#!/usr/bin/env python3
"""备用策略清单（`configs/shortlist_arms.tsv`）→ `sweep_backtest_configs.py` 的两份配置。

清单每行一条臂，列：
  label        臂名
  group        分组（只作展示）
  states_from  `-` = 读生产逐日状态；`self` = 用本行 build_extra／divspread 重建两侧状态；其它 = 复用该臂的状态与买入线
  build_extra  建带追加开关（相对 §6.7 第 2 步），`-` = 不改建带
  divspread    银行/保险股利折现利差，`-` = 生产值（§6.7 第 3 步）
  universe     宇宙面板路径，`-` = 生产宇宙；给了就只重解买入线
  rule_extra   扫描器额外参数（相对 BASE），`-` = 无
  note         一句话

输出：
  <exp>/configs/shortlist_rules.txt   只动规则／参数的臂（不需要重建）
  <exp>/configs/shortlist_val.txt     需要两侧逐日状态或换宇宙的臂；`--width` 从 <exp>/val/<臂>/align_buy_line.txt 读
  --list-builds                        只打印要先建的臂（label\tbuild_extra\tdivspread\tuniverse），供 submit 脚本用
"""
import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_arms(tsv: Path):
    with tsv.open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh, delimiter="\t") if r.get("label") and not r["label"].startswith("#")]


def width_from_align(path: Path) -> str:
    m = re.search(r"--width (-?\d+\.\d+)", path.read_text(encoding="utf-8"))
    if not m:
        sys.exit(f"{path} 里读不到 `--width`")
    return m.group(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=Path, default=ROOT / "data/experiments/exp_strategy_shortlist")
    ap.add_argument("--tsv", type=Path, default=None, help="缺省 <exp>/configs/shortlist_arms.tsv")
    ap.add_argument("--list-builds", action="store_true")
    args = ap.parse_args()
    tsv = args.tsv or args.exp / "configs/shortlist_arms.tsv"
    arms = read_arms(tsv)
    by_label = {r["label"]: r for r in arms}

    def needs_build(r):
        return r["states_from"] == "self" or r["universe"] != "-"

    if args.list_builds:
        for r in arms:
            if needs_build(r):
                print("\t".join([r["label"], r["build_extra"], r["divspread"], r["universe"]]))
        return

    rules = [f"# 备用策略清单（{tsv.relative_to(ROOT)}）：只动规则／参数的臂，逐日状态、宇宙、两线沿用当前 BASE。", "BASE|"]
    val = [f"# 备用策略清单（{tsv.relative_to(ROOT)}）：需重建两侧逐日状态或换宇宙的臂；买入线各自按 §12.30 重解到同一在册合格面，换仓边际沿用在册。", "BASE|"]
    missing = []
    for r in arms:
        if r["label"] == "BASE":
            continue
        extra = "" if r["rule_extra"] == "-" else r["rule_extra"]
        src = r["states_from"]
        if src == "-" and r["universe"] == "-":
            rules.append(f"{r['label']}|{extra}")
            continue
        base_arm = r["label"] if (src == "self" or r["universe"] != "-") else src
        base_row = by_label.get(base_arm)
        if base_row is None:
            sys.exit(f"{r['label']} 的 states_from={src} 不在清单里")
        align = args.exp / "val" / base_arm / "align_buy_line.txt"
        if not align.exists():
            missing.append(base_arm)
            continue
        width = width_from_align(align)
        if base_row["universe"] != "-":
            parts = [f"--universe-file {base_row['universe']} --width {width}"]
        else:
            d = args.exp / "val" / base_arm
            parts = [f"--daily-states {d}/states_base.csv --hold-states {d}/states_hold.csv --width {width}"]
        if extra:
            parts.append(extra)
        val.append(f"{r['label']}|{' '.join(parts)}")
    if missing:
        sys.exit("以下臂的两侧状态／买入线重解尚未落盘（先跑 scripts/slurm/submit_strategy_shortlist.sh）：" + "、".join(sorted(set(missing))))
    (args.exp / "configs/shortlist_rules.txt").write_text("\n".join(rules) + "\n", encoding="utf-8")
    (args.exp / "configs/shortlist_val.txt").write_text("\n".join(val) + "\n", encoding="utf-8")
    print(f"规则臂 {len(rules) - 2} 条 → configs/shortlist_rules.txt；估值／宇宙臂 {len(val) - 2} 条 → configs/shortlist_val.txt")


if __name__ == "__main__":
    main()
