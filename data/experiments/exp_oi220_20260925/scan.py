"""Republish the signal day (EXP_SIGNAL, default 2026-09-24) on the landed valuations with the user's reported account (§9.1 第 5 步)."""
import os
import subprocess
import sys
from datetime import datetime, timezone

from common import EXP, ROOT, load, read, unchanged_since_freeze
sys.path.insert(0, str(ROOT / 'scripts'))
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION

SIGNAL = os.environ.get('EXP_SIGNAL', '2026-09-24')


def main():
    for name in ('a_share_holdings.csv', 'portfolio_account_snapshot.csv'):
        assert unchanged_since_freeze('data/processed/' + name), name
    run_id = 'OI-220-20260925'
    ruling = load('user_ruling.json')
    if not any(r['run_id'] == run_id for r in read(DEFAULT_DECISION_LOG)):
        append_decision_log(DEFAULT_DECISION_LOG, [dict(
            logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage='mechanism_repair', run_id=run_id, as_of=SIGNAL,
            security_code='ALL', decision_type='valuation_caliber', decision_result='adopted',
            summary_reason=f"OI-220：为应付票据质押、按经营资产计入投入资本的现金类同时计入经营营运资金（与其担保的应付票据相抵），资本腿再投资率计入其变动（`--restricted-cash notes_wc`）。买入线 {ruling.get('buy_line', '不变')}（原线合格面 {ruling['old_line_share_pct']}%，在容差内保留）、换仓边际 {ruling.get('swap_margin', 0.15)}。用户 2026-09-25 裁定按原则落地，轨道 A 记录见 verification.json。",
            input_files=str(EXP / 'verification.json'), output_file=str(EXP / 'publication.json'),
            operator_or_script='exp_oi220_20260925/scan.py', workflow_version=WORKFLOW_VERSION)])
    account = next(r for r in read(ROOT / 'data/processed/portfolio_account_snapshot.csv') if r['as_of'] == SIGNAL)
    subprocess.run([sys.executable, str(ROOT / 'scripts/screen_daily_volume_price_signals.py'), '--as-of', SIGNAL,
                    '--review-queue', 'data/interim/a_share_report_update_queue.csv',
                    '--model-bands', 'data/processed/a_share_pool_model_bands_adopted.csv',
                    '--hold-bands', 'data/processed/a_share_pool_model_bands_hold.csv',
                    '--nav', account['net_assets_cny'], '--funds', '0', '--cash', account['cash_cny'] or '0',
                    '--debt', account['margin_debt_cny'], '--workers', '16'], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
