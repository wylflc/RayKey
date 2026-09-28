#!/usr/bin/env python3
"""OI-226：OI-150 海外估值前向检验（`scripts/experimental/oi150_complete.py`，内部调用 `overseas_pv_forward`）按现行
估值口径重跑 value／report，产物改写到本实验目录 `oi150/`，OI-150 已结案记录（exp_oi150_overseas_forward/）不动。

输入（股票池、价格来源表、执行记录）从 OI-150 目录复制到 `oi150/`；SEC 原始事实与价格缓存仍读 OI-150 的 raw/。
用法：python3 tools/oi150_rerun.py value --workers 16 ；python3 tools/oi150_rerun.py report
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
ROOT = EXP.parents[2]
OUT = EXP / "oi150"
INPUTS = ("universe.csv", "universe_ciks.csv", "price_sources.csv", "execution_20260907.md")


def main() -> int:
    sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "scripts/experimental")]
    import oi150_complete as study  # noqa: E402
    OUT.mkdir(parents=True, exist_ok=True)
    for name in INPUTS:
        src, dst = study.EXP / name, OUT / name
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            shutil.copyfile(src, dst)
    study.EXP = OUT                      # value()/report() 读写的 EXP 改指本目录；RAW／PRICE_DIR 仍是 OI-150 的缓存
    sys.argv = ["oi150_complete.py", *sys.argv[1:]]
    study.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
