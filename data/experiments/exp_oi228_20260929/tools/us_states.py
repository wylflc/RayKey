#!/usr/bin/env python3
"""OI-228 美股历史状态重建（`scripts/build_us_daily_states.py` 现行代码）：逐申报带与覆盖率写本目录 `us/`，
逐日状态写 `--out`（候选阶段写本目录 `us/states_adopted.csv`，不覆盖生产文件）。

用法：python3 tools/us_states.py [--workers N] [--out PATH]
"""
from __future__ import annotations

import sys
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
ROOT = EXP.parents[2]


def main() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "scripts/experimental"))
    import build_us_daily_states as bus  # noqa: E402
    bus.BANDS_OUT = EXP / "us" / "us_valuation_bands.csv"
    bus.COVER_OUT = EXP / "us" / "valuation_coverage.csv"
    sys.argv = ["build_us_daily_states.py", *sys.argv[1:]]
    return bus.main()


if __name__ == "__main__":
    raise SystemExit(main())
