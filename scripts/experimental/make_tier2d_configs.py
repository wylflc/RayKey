"""§12.177 第二轮：买入一档 × 卖出一档的二维档位扫描配置（用户 2026-09-02：两档不必相等，先粗后细）。

用法：
  python3 scripts/experimental/make_tier2d_configs.py --extra "<定下的口径开关>" \
      --buy 2.5,5,7.5,10 --sell 2.5,5,7.5,10 --out <配置文件>
`--extra` 是已裁定的口径（如 `--gain-ladder ... --swap-mode pairwise --swap-margin 0.15 --swap-sell-set weak`），
每臂 = extra + `--x <买入档> --sell-x <卖出档>`；对照臂 BASE = extra 本身（5%／5%），Δ 只在该口径内比较。
标签 `Bxx_Syy`（去掉小数点，如 B25_S75 = 买 2.5%／卖 7.5%）。
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", default="", help="已裁定的口径开关，写进每臂（含 BASE 臂）")
    ap.add_argument("--buy", default="2.5,5,7.5,10")
    ap.add_argument("--sell", default="2.5,5,7.5,10")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    buys = [float(v) for v in args.buy.split(",")]
    sells = [float(v) for v in args.sell.split(",")]
    lines = [f"# §12.177 第二轮二维档位扫描：对照臂 BASE = 口径「{args.extra or '生产 BASE'}」× 买 5%／卖 5%。",
             f"BASE|{args.extra}".rstrip()]
    for b in buys:
        for s in sells:
            if b == 5.0 and s == 5.0:
                continue
            tag = f"B{b:g}_S{s:g}".replace(".", "")
            sell_flag = f" --sell-x {s:g}" if s != b else f" --sell-x {s:g}"
            lines.append(f"{tag}|{args.extra} --x {b:g}{sell_flag}".replace("|  ", "| ").replace("| ", "|"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(lines) - 1} 臂 → {args.out}")


if __name__ == "__main__":
    main()
