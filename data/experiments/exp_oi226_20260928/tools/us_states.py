#!/usr/bin/env python3
"""OI-226 美股历史状态重建（标普 500 历史成分，`scripts/build_us_daily_states.py` 同一实现）。

变体（逐申报带写本目录 `us/`，OI-159／OI-210 原记录不动）：
  current  现行代码 → data/processed/us_daily_states_adopted.csv（逐日状态），带与覆盖率 us/us_valuation_bands.csv
  pre4214  现行估值引擎 + OI-216 之前（20d28beb^）的 fetch_overseas_statements：归因 OI-216 标签组改动
  oi210    OI-210 重建时（ee4a0325）的 fetch_overseas_statements 与 build_overseas_roic_bands：复现 09-24 的带
非 current 变体须给 --out（逐日状态只作中间产物，写作业临时目录）。

用法：python3 tools/us_states.py [--variant current|pre4214|oi210] [--bands-dir us] [--workers N] [--out PATH]
--bands-dir：逐申报带与覆盖率写本目录下哪个子目录（第一轮 us/，第二轮台积电余项 us_r2/）。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
ROOT = EXP.parents[2]
VARIANTS = {"current": {}, "pre4214": {"fetch_overseas_statements": "20d28beb^"},
            "oi210": {"fetch_overseas_statements": "ee4a0325", "build_overseas_roic_bands": "ee4a0325"}}


def preload(module: str, rev: str, tmp: Path) -> None:
    """把 `rev` 版本的 scripts/<module>.py 以原模块名装入 sys.modules（build_us_daily_states 随后 import 即取到它）。"""
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:scripts/{module}.py"], check=True,
                            capture_output=True, text=True).stdout
    anchor = "ROOT = Path(__file__).resolve().parents[1]"
    assert source.count(anchor) == 1, f"{module}@{rev}: ROOT anchor not found"
    source = source.replace(anchor, f"ROOT = Path({str(ROOT)!r})")   # 模块常量仍指向仓库
    path = tmp / f"{module}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(module, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module] = mod
    spec.loader.exec_module(mod)


def main() -> int:
    args = sys.argv[1:]
    variant = "current"
    if "--variant" in args:
        i = args.index("--variant")
        variant = args[i + 1]
        del args[i:i + 2]
    if variant not in VARIANTS:
        raise SystemExit(f"unknown variant {variant}")
    bands_dir = "us"
    if "--bands-dir" in args:
        i = args.index("--bands-dir")
        bands_dir = args[i + 1]
        del args[i:i + 2]
    if variant != "current" and "--out" not in args:
        raise SystemExit("non-current variants need --out (scratch path for the daily states)")
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "scripts/experimental"))
    tmp = Path(tempfile.mkdtemp(prefix=f"oi226_{variant}_"))
    # 依赖顺序：先取数模块，再估值引擎（旧引擎只 import roic_inputs／minority_claims／intrinsic_value）
    for module in ("fetch_overseas_statements", "build_overseas_roic_bands"):
        rev = VARIANTS[variant].get(module)
        if rev:
            preload(module, rev, tmp)
    import build_us_daily_states as bus  # noqa: E402
    suffix = "" if variant == "current" else f"_{variant}"
    bus.BANDS_OUT = EXP / bands_dir / f"us_valuation_bands{suffix}.csv"
    bus.COVER_OUT = EXP / bands_dir / f"valuation_coverage{suffix}.csv"
    print(f"variant={variant} fos={bus.fos.__file__} bor={bus.bor.__file__}", flush=True)
    sys.argv = ["build_us_daily_states.py", *args]
    return bus.main()


if __name__ == "__main__":
    raise SystemExit(main())
