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
    run_id = 'OI-217-20260925'
    ruling = load('user_ruling.json')
    if not any(r['run_id'] == run_id for r in read(DEFAULT_DECISION_LOG)):
        append_decision_log(DEFAULT_DECISION_LOG, [dict(
            logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage='mechanism_repair', run_id=run_id, as_of=SIGNAL,
            security_code='ALL', decision_type='valuation_caliber', decision_result='adopted',
            summary_reason=f"OI-217：r 作资产要求回报、不随资本结构变，企业价值与零增长锚一律按 r = 10% 折现（WACC = r，不按资本结构加权、不计债务税盾，债务只经股权桥扣减，`--wacc-weights unlevered`）；海外 §6.8 同式。买入线 0.9524 → {ruling['buy_line']}（原线合格面 {ruling['old_line_share_pct']}% 超出容差、重解到 {ruling['registered_share_pct']}%）、换仓边际 {ruling.get('swap_margin', 0.15)}。用户 2026-09-25 裁定按原则采纳（轨道 A 护栏不过，公允性检验净负债组偏差最小），记录见 verification.json 与 exp_oi217f2_20260925。",
            input_files=str(EXP / 'verification.json'), output_file=str(EXP / 'publication.json'),
            operator_or_script='exp_oi217u2_20260925/scan.py', workflow_version=WORKFLOW_VERSION)])
    account = next(r for r in read(ROOT / 'data/processed/portfolio_account_snapshot.csv') if r['as_of'] == SIGNAL)
    subprocess.run([sys.executable, str(ROOT / 'scripts/screen_daily_volume_price_signals.py'), '--as-of', SIGNAL,
                    '--review-queue', 'data/interim/a_share_report_update_queue.csv',
                    '--model-bands', 'data/processed/a_share_pool_model_bands_adopted.csv',
                    '--hold-bands', 'data/processed/a_share_pool_model_bands_hold.csv',
                    '--nav', account['net_assets_cny'], '--funds', '0', '--cash', account['cash_cny'] or '0',
                    '--debt', account['margin_debt_cny'], '--workers', '16'], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
