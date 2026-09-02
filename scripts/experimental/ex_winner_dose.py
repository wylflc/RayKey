#!/usr/bin/env python3
"""剔除赢家只数的剂量曲线（§12.1 第 4 款②）：K = 1／3／5／10，赢家取 `BASE` 锚定起点闭合周期按代码汇总的已实现盈亏前 K 名。

每档 K 下把同一组代码用 `--exclude-codes` 从配置里**全部臂**统一剔除、跑标准起点集，结果行沿用
`ex_winner_symmetry.py` 的格式（`#SET|K<k>|codes` ＋ `EX5:K<k><label>|since|…`），
用 `ex_winner_symmetry_report.py --challenger <臂>` 汇总成表；四档读数须同向才算过第 4 款②。

用法：ex_winner_dose.py <configs.txt> --trades <BASE 锚定起点 *_trades.csv> --out <file> [--ks 1,3,5,10] [--workers N]
"""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/experimental"))
from delta_attribution import load_pnl  # noqa: E402
from sweep_backtest_configs import DEFAULT_STARTS, run_one  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", type=Path)
    ap.add_argument("--trades", type=Path, required=True, help="BASE 锚定起点长跑的闭合周期文件（*_trades.csv）")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ks", default="1,3,5,10")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--starts", default="")
    args = ap.parse_args()

    starts = [s.strip() for s in args.starts.split(",") if s.strip()] or DEFAULT_STARTS
    arms = []
    for line in args.config.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            label, extra = line.split("|", 1)
            arms.append((label.strip(), extra))
    ranked = sorted(load_pnl(args.trades).items(), key=lambda kv: -kv[1])
    print("赢家排序（已实现盈亏，亿）：" + "、".join(f"{c} {v/1e8:.2f}" for c, v in ranked[:12]), file=sys.stderr)

    with args.out.open("w", encoding="utf-8") as fh:
        for k in (int(x) for x in args.ks.split(",")):
            codes = [c for c, _ in ranked[:k]]
            tag = f"K{k}"
            fh.write(f"#SET|{tag}|{','.join(codes)}\n")
            jobs = [(f"{tag}{label}", extra, s, ",".join(codes)) for label, extra in arms for s in starts]
            print(f"剔除前 {k} 名（{','.join(codes)}）：{len(jobs)} 次运行，{args.workers} 并发", file=sys.stderr)
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for done, result in enumerate(pool.map(run_one, jobs), 1):
                    fh.write(result + "\n")
                    fh.flush()
                    if done % 25 == 0:
                        print(f"  {done}/{len(jobs)}", file=sys.stderr)


if __name__ == "__main__":
    main()
