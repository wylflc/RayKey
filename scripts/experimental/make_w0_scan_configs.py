#!/usr/bin/env python3
"""OI-124：`W=0` 转基准后的两条线剂量扫描配置生成（§12.1 第 5 款要扫相邻区间取宽平台）。

`BASE` 行留空 = 读生产文件与在册常量（换基准后即 W=0 链）。各臂只动一个旋钮：
  margin  换仓阈值 `--swap-margin` 0.10~0.30 一档 0.01
  poscap  单票买入上限 `--position-cap` 0.20~1.00 一档 0.05
  credit  授信比例 `--credit-ratio` 0.0~1.20 一档 0.10（「仓位上限」的另一读法）

用法：make_w0_scan_configs.py --out-dir data/processed/experiments/exp_oi124_w0base/configs
"""
import argparse
from pathlib import Path


def frange(lo: float, hi: float, step: float) -> list[float]:
    n = round((hi - lo) / step)
    return [round(lo + i * step, 4) for i in range(n + 1)]


SCANS = {
    "margin": ("--swap-margin", frange(0.10, 0.30, 0.01), "SM", 100, 0.19),
    "poscap": ("--position-cap", frange(0.20, 1.00, 0.05), "PC", 100, 0.60),
    "credit": ("--credit-ratio", frange(0.00, 1.20, 0.10), "CR", 100, 0.666),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, (flag, values, prefix, scale, current) in SCANS.items():
        lines = [f"# OI-124 {name} 剂量扫描：{flag} {values[0]}~{values[-1]}。",
                 f"# BASE 行留空 = 生产在册值（现行 {flag} {current}）；各臂只动这一个旋钮。",
                 "BASE|"]
        for v in values:
            if abs(v - current) < 1e-9:      # 与在册值同点的臂由 BASE 承担，不重复跑
                continue
            lines.append(f"{prefix}{round(v * scale):03d}|{flag} {v}")
        path = args.out_dir / f"{name}_arms.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{path}：{len(lines) - 3} 臂 + BASE")


if __name__ == "__main__":
    main()
