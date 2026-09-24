"""OI-210 美股历史状态重建：新口径引擎 → data/processed/us_daily_states_adopted.csv；逐申报带与覆盖率写本目录 us/（OI-159 原记录不动）。"""
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_us_daily_states as bus  # noqa: E402

bus.BANDS_OUT = EXP / 'us' / 'us_valuation_bands.csv'
bus.COVER_OUT = EXP / 'us' / 'valuation_coverage.csv'
sys.argv = ['build_us_daily_states.py', *sys.argv[1:]]
raise SystemExit(bus.main())
