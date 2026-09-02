"""把若干条臂的 14 起点全样本行（各自扫描文件里的 `BASE|` 行）与生产 `BASE` 行合成一份扫描文件，
交给 `sweep_backtest_configs.report` 出 Δ 表（§12.1 第 2 款五项决策读数＋闸门）。

用法：
  python3 scripts/experimental/arms_vs_base_report.py --base <含生产 BASE 行的扫描文件> \
      --arm C100=<扫描文件> --arm G110U=<扫描文件> --out <合成文件> [--title ...]
臂扫描文件里以 `BASE|` 开头的行被改名为该臂标签；`EX5:` 行一律丢弃（两份文件的剔除集可能不同，不可混比）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sbc  # noqa: E402


def base_rows(path: Path) -> list[str]:
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("BASE|")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--arm", action="append", default=[], metavar="LABEL=FILE")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--title", default="各臂对生产 BASE（14 起点全样本）")
    args = ap.parse_args()
    lines = base_rows(args.base)
    for spec in args.arm:
        label, file = spec.split("=", 1)
        rows = base_rows(Path(file))
        lines += [label + l[len("BASE"):] for l in rows]
        print(f"{label}: {len(rows)} 行", file=sys.stderr)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sbc.report(args.out, args.title)


if __name__ == "__main__":
    main()
