"""Shared paths and helpers for the OI-200～203 Track-A experiment."""
import csv
import hashlib
import json
import subprocess
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
STATE_FILES = ('roic_bands.csv', 'roic_bands_b2.csv', 'roic_daily_raw.csv', 'roic_daily_raw_b2.csv',
               'a_share_daily_states_adopted.csv', 'a_share_daily_states_b2.csv', 'a_share_daily_states_hold.csv')
ARMS = ('CONTROL', 'MID', 'NEW')
FLAGS = {'CONTROL': ['--cash-caliber', 'legacy', '--equity-anchor', 'legacy'],
         'MID': ['--cash-caliber', 'legacy', '--equity-anchor', 'guarded'],
         'NEW': ['--cash-caliber', 'nonop', '--equity-anchor', 'guarded']}
# §6.7 第 2 步命令（生产口径两项由 FLAGS 按臂给出）
PRODUCTION = ['--all', '--value-model', 'roic', '--roe-source', 'onesided_max', '--roe-lift', '2.0', '--uniform-tier', 'L2',
              '--since', '2002-01-01', '--roic-nopat-source', 'conditional3', '--roic-growth', 'hybrid',
              '--roic-cycle-guard', 'peak', '--roic-cond-detect', 'graded', '--roic-peak-ramp', '0.3',
              '--ttm-current', 'on', '--growth-damp', 'on', '--thin-equity-max', '0.5', '--roic-trail-weight', '0',
              '--minority-basis', 'earnings', '--wc-aggregation', 'operating']
B2 = ['--ttm-trust', 'on', '--ttm-trust-delta', '0.02']
OI202_OUTPUT_COLUMNS = {'roic_g_source', 'valuation_quality_score', 'valuation_quality_notes'}
FROZEN_ACTIONS = EXP / 'old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'
PANEL = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'


def unchanged_since_freeze(rel: str) -> bool:
    """Account files were not copied into old_inputs; compare the live file with the freeze revision's blob."""
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
        'data/reference/cash_note_items.csv', 'data/reference/panel_restatement_originals.csv',
        'data/reference/cost_of_equity_inputs.csv', 'data/reference/equity_bond_csi300.csv',
        'data/reference/financials_corrections.csv', 'data/reference/a_share_code_succession.csv',
        'data/processed/entity_reset_dates.csv', 'data/processed/share_event_reviews.csv',
        'data/interim/statement_restatements.csv', 'data/interim/restatement_announcements.csv',
        'data/processed/pit_attention/panel_moat_bank_v6b.csv', 'data/processed/a_share_watchlist_quality_tiers.csv')]
    return [p for p in files if p.exists()]
