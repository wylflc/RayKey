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
    run_id = 'OI-219-20260925'
    ruling = load('user_ruling.json')
    if not any(r['run_id'] == run_id for r in read(DEFAULT_DECISION_LOG)):
        append_decision_log(DEFAULT_DECISION_LOG, [dict(
            logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage='mechanism_repair', run_id=run_id, as_of=SIGNAL,
            security_code='ALL', decision_type='valuation_caliber', decision_result='adopted',
            summary_reason=f"OI-219：年报受限资产附注中为应付票据、信用证、保函质押的现金类按经营资产计入投入资本（以当期应付票据与现金类为限），其利息并回 EBIT，应付票据仍为经营负债、WACC 不变（`--restricted-cash notes`）。买入线 {ruling.get('buy_line', '不变')}（原线合格面 {ruling['old_line_share_pct']}%，在容差内保留）、换仓边际 {ruling.get('swap_margin', 0.15)}。用户 2026-09-25 裁定，轨道 A 记录见 verification.json。",
            input_files=str(EXP / 'verification.json'), output_file=str(EXP / 'publication.json'),
            operator_or_script='exp_oi219_20260925/scan.py', workflow_version=WORKFLOW_VERSION)])
    account = next(r for r in read(ROOT / 'data/processed/portfolio_account_snapshot.csv') if r['as_of'] == SIGNAL)
    subprocess.run([sys.executable, str(ROOT / 'scripts/screen_daily_volume_price_signals.py'), '--as-of', SIGNAL,
                    '--review-queue', 'data/interim/a_share_report_update_queue.csv',
                    '--model-bands', 'data/processed/a_share_pool_model_bands_adopted.csv',
                    '--hold-bands', 'data/processed/a_share_pool_model_bands_hold.csv',
                    '--nav', account['net_assets_cny'], '--funds', '0', '--cash', account['cash_cny'] or '0',
                    '--debt', account['margin_debt_cny'], '--workers', '16'], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
