"""长跑持仓延至 2026-09-29（描述性，不改任何规则）：共用路径与代码清单。

在册回测输入的行情缓存多数只到 2026-08-07（141 只到 08-28），逐日状态随之截止。本实验在实验目录内
把回测宇宙（面板 295 只）与全部银行保险（H2 截面系数须同一批银行）的行情续到 09-29，
按 §6.7 第 2／2b／3 步原命令重建两侧逐日状态与持仓侧状态，再用现行 `BASE`（v4.222）与
v4.221 `BASE` 从标准起点长跑到 09-29。`data/raw/ohlcv/` 与 `data/processed/` 一律不写。
"""
import csv
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

UNTIL = '2026-09-29'
SRC_OHLCV = ROOT / 'data/raw/ohlcv'
OHLCV = EXP / 'ohlcv'
STATES = EXP / 'states'
PANEL_STATES = STATES / 'panel'
PANEL = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
DC = ROOT / 'data/experiments/exp_oi230_20260929/states/DC'      # 在册读数（OI-237、v4.222 落地）所用的面板子集状态
INDEXES = {'INDEX_000001': 'sh000001', 'INDEX_000300': 'sh000300'}
S15_FLAGS = ' --bt-quiet 3 --no-trend-stop --swap-ext 0.30 0.15 0'
# §6.7 第 2 步命令（`--all` 换成本实验的代码清单）
PRODUCTION = ['--value-model', 'roic', '--roe-source', 'onesided_max', '--roe-lift', '2.0', '--uniform-tier', 'L2',
              '--since', '2002-01-01', '--roic-nopat-source', 'conditional3', '--roic-growth', 'hybrid',
              '--roic-cycle-guard', 'peak', '--roic-cond-detect', 'graded', '--roic-peak-ramp', '0.3',
              '--ttm-current', 'on', '--growth-damp', 'on', '--thin-equity-max', '0.5', '--roic-trail-weight', '0',
              '--minority-basis', 'earnings', '--wc-aggregation', 'operating', '--cash-caliber', 'nonop',
              '--equity-anchor', 'guarded', '--restricted-cash', 'notes_wc', '--wacc-weights', 'unlevered',
              '--reset-guard', 'both', '--rd-capitalize', 'on', '--fade-shape', 'exponential', '--fade-lambda', '0.12',
              '--fade-horizon', '50', '--roic-ic-floor', '0.1']
B2 = ['--ttm-trust', 'on', '--ttm-trust-delta', '0.02']
BANK_MODE = 'h2:0.02:0.10'


def read(path: Path) -> list[dict]:
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def securities() -> dict[str, tuple[str, str]]:
    return {r['security_code'].zfill(6): (r.get('security_name', ''), r.get('exchange', ''))
            for r in read(ROOT / 'data/raw/a_share_securities.csv')}


def panel_codes() -> set[str]:
    return {r['security_code'] for r in read(PANEL)}


def financial_codes() -> set[str]:
    """全部有行情文件的银行保险：H2 当日截面系数 G 取当日全部银行，只建面板银行会改变 G。"""
    from divspread_names import is_divspread_financial
    names = securities()
    return {p.stem for p in SRC_OHLCV.glob('*.csv')
            if not p.stem.startswith('INDEX') and is_divspread_financial(p.stem, names.get(p.stem, ('', ''))[0])}


def build_codes() -> list[str]:
    return sorted(panel_codes() | financial_codes())
