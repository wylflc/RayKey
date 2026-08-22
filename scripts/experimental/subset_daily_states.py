#!/usr/bin/env python3
"""把全市场逐日估值状态按若干股票库面板的代码并集切成子集文件（只为回测提速，逐位等价，回测日志 §12.94.6）。

用法：
    python3 scripts/experimental/subset_daily_states.py data/processed/a_share_daily_states_adopted.csv \
        --out-dir data/processed/experiments/states  <panel1.csv> [<panel2.csv> ...]

每个面板产出 `states_<面板文件名>.csv`，一遍流式读完源文件。
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("states", type=Path)
    ap.add_argument("panels", nargs="+", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    unions: dict[Path, set[str]] = {}
    for panel in args.panels:
        with panel.open(newline="", encoding="utf-8-sig") as fh:
            unions[panel] = {r["security_code"].zfill(6) for r in csv.DictReader(fh)}
    outs = {}
    for panel, codes in unions.items():
        path = args.out_dir / f"states_{panel.stem}.csv"
        fh = path.open("w", newline="", encoding="utf-8")
        outs[panel] = (fh, csv.writer(fh), codes, [0])
    with args.states.open(newline="", encoding="utf-8") as src:
        reader = csv.reader(src)
        header = next(reader)
        i_code = header.index("security_code")
        for fh, w, codes, n in outs.values():
            w.writerow(header)
        for row in reader:
            code = row[i_code]
            for fh, w, codes, n in outs.values():
                if code in codes:
                    w.writerow(row)
                    n[0] += 1
    for panel, (fh, w, codes, n) in outs.items():
        fh.close()
        print(f"{panel.stem:<24} 并集 {len(codes):>5} 只 → {n[0]:>10,} 行 → {args.out_dir / ('states_' + panel.stem + '.csv')}")


if __name__ == "__main__":
    main()
