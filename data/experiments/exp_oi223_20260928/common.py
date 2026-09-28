"""Shared paths and helpers for the OI-223 discount-rate tier test on v4.215 (preregister.md)."""
import csv
import hashlib
import json
import subprocess
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
STATE_FILES = ('roic_bands.csv', 'roic_bands_b2.csv', 'roic_daily_raw.csv', 'roic_daily_raw_b2.csv',
               'a_share_daily_states_adopted.csv', 'a_share_daily_states_b2.csv', 'a_share_daily_states_hold.csv')
ARMS = ('CONTROL', 'TIERS')
# TIERS（OI-223）：逐票时点折现率档 8%～12%（build_discount_rate_tiers.py 由冻结的现行带生成），终值超额不变
TIERS_FILE = EXP / 'discount_rate_tiers_pit.csv'
FLAGS = {'CONTROL': [], 'TIERS': ['--discount-tiers', str(TIERS_FILE)]}
BANK_MODE = 'h2:0.02:0.10'                   # §6.7 第 3 步（v4.215，OI-207 H2），两臂相同
# §6.7 第 2 步命令（v4.215 生产口径：v4.213 + 银行 H2；建带命令同 v4.213）
PRODUCTION = ['--all', '--value-model', 'roic', '--roe-source', 'onesided_max', '--roe-lift', '2.0', '--uniform-tier', 'L2',
              '--since', '2002-01-01', '--roic-nopat-source', 'conditional3', '--roic-growth', 'hybrid',
              '--roic-cycle-guard', 'peak', '--roic-cond-detect', 'graded', '--roic-peak-ramp', '0.3',
              '--ttm-current', 'on', '--growth-damp', 'on', '--thin-equity-max', '0.5', '--roic-trail-weight', '0',
              '--minority-basis', 'earnings', '--wc-aggregation', 'operating', '--cash-caliber', 'nonop',
              '--equity-anchor', 'guarded', '--restricted-cash', 'notes_wc', '--wacc-weights', 'unlevered', '--reset-guard', 'both',
              '--fade-shape', 'exponential', '--fade-lambda', '0.12', '--fade-horizon', '50',
              '--roic-ic-floor', '0.1']
B2 = ['--ttm-trust', 'on', '--ttm-trust-delta', '0.02']
LABEL_COLUMNS: set[str] = set()              # CONTROL 须逐行复现现存状态
FROZEN_ACTIONS = EXP / 'old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'
PANEL = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
# 盘后作业每晚刷新的两份输入：只追加或改写回测末日之后的行时，按有效输入不变处理（run.py 收尾逐行核对）
NIGHTLY = ('data/reference/cost_of_equity_inputs.csv', 'data/reference/equity_bond_csi300.csv')
REGISTERED_SHARE = 0.17777                   # 在册合格面（v4.215 买入线 1.0495 重解到此面，回测日志 §12.274）


def unchanged_since_freeze(rel: str) -> bool:
    rev = json.loads((EXP / 'before_manifest.json').read_text())['revision']
    blob = subprocess.check_output(['git', 'show', f'{rev}:{rel}'], cwd=ROOT)
    return (ROOT / rel).read_bytes() == blob


def digest(path: Path) -> dict:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 22), b''):
            h.update(block)
    return dict(bytes=path.stat().st_size, sha256=h.hexdigest())


def save(name: str, value) -> None:
    (EXP / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def load(name: str):
    return json.loads((EXP / name).read_text())


def read(path: Path) -> list[dict]:
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def panel_codes() -> set[str]:
    return {r['security_code'] for r in read(PANEL)}


def input_files() -> list[Path]:
    """建带与回测读取的全部输入（除现存历史状态）；前后哈希一致才算冻结有效。"""
    files = sorted((ROOT / 'data/raw/financials').rglob('*.csv')) + sorted((ROOT / 'data/raw/financials_statements').rglob('*.csv'))
    files += sorted((ROOT / 'data/raw/ohlcv').glob('*.csv'))
    files += [ROOT / p for p in (
        'data/reference/a_share_exright_terms.csv', 'data/reference/a_share_action_component_corrections.csv',
        'data/reference/minority_claim_events.json', 'data/reference/consolidation_events.csv',
        'data/reference/cash_note_items.csv', 'data/reference/restricted_cash_items.csv', 'data/reference/panel_restatement_originals.csv',
        'data/reference/cost_of_equity_inputs.csv', 'data/reference/equity_bond_csi300.csv',
        'data/reference/financials_corrections.csv', 'data/reference/a_share_code_succession.csv',
        'data/processed/entity_reset_dates.csv', 'data/processed/share_event_reviews.csv',
        'data/interim/statement_restatements.csv', 'data/interim/restatement_announcements.csv',
        'data/processed/pit_attention/panel_moat_bank_v6b.csv', 'data/processed/a_share_watchlist_quality_tiers.csv',
        'data/interim/strategy_tag_map.csv', 'data/reference/cycle_guard_supplement.csv',
        'data/reference/entity_reset_guard_anchor.csv')]
    return [p for p in files if p.exists()]
