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
    run_id = 'OI-215-20260925'
    ruling = load('user_ruling.json')
    if not any(r['run_id'] == run_id for r in read(DEFAULT_DECISION_LOG)):
        append_decision_log(DEFAULT_DECISION_LOG, [dict(
            logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage='mechanism_repair', run_id=run_id, as_of=SIGNAL,
            security_code='ALL', decision_type='valuation_caliber', decision_result='adopted',
            summary_reason=f"OI-215：年报附注现金类解析补认只写两个年份或「账面余额」的表头与丢了序号的标题，中国海油、嘉立创按原文人工核定（`data/reference/cash_note_manual.csv`），弃置费专户存款按经营资产；附注表与受限资产表按现行规则重解析后重建状态。买入线 {ruling.get('buy_line', '不变')}（原线合格面 {ruling['old_line_share_pct']}%）、换仓边际 {ruling.get('swap_margin', 0.15)}。用户 2026-09-25 裁定先落地附注修正，轨道 A 记录见 verification.json。",
            input_files=str(EXP / 'verification.json'), output_file=str(EXP / 'publication.json'),
            operator_or_script='exp_oi215_20260925/scan.py', workflow_version=WORKFLOW_VERSION)])
    account = next(r for r in read(ROOT / 'data/processed/portfolio_account_snapshot.csv') if r['as_of'] == SIGNAL)
    subprocess.run([sys.executable, str(ROOT / 'scripts/screen_daily_volume_price_signals.py'), '--as-of', SIGNAL,
                    '--review-queue', 'data/interim/a_share_report_update_queue.csv',
                    '--model-bands', 'data/processed/a_share_pool_model_bands_adopted.csv',
                    '--hold-bands', 'data/processed/a_share_pool_model_bands_hold.csv',
                    '--nav', account['net_assets_cny'], '--funds', '0', '--cash', account['cash_cny'] or '0',
                    '--debt', account['margin_debt_cny'], '--workers', '16'], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
