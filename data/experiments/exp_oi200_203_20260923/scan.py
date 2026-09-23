"""Republish the 2026-09-23 signal day on the landed valuations with the user's reported account (§9.1 第 5 步)."""
import subprocess
import sys
from datetime import datetime, timezone

from common import EXP, ROOT, read, unchanged_since_freeze
sys.path.insert(0, str(ROOT / 'scripts'))
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION

SIGNAL = '2026-09-23'


def main():
    for name in ('a_share_holdings.csv', 'portfolio_account_snapshot.csv'):
        assert unchanged_since_freeze('data/processed/' + name), name
    run_id = 'OI-200-203-20260923'
    if not any(r['run_id'] == run_id for r in read(DEFAULT_DECISION_LOG)):
        append_decision_log(DEFAULT_DECISION_LOG, [dict(
            logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage='mechanism_repair', run_id=run_id, as_of=SIGNAL,
            security_code='ALL', decision_type='valuation_caliber', decision_result='adopted',
            summary_reason='OI-200～203：类金融按总资产 20% 识别走权益口径并补 λ 锚与峰谷守卫；非经营金融资产按账面计入、金融收益不进 EBIT、附注核定存款计现金；五粮液 2025 季报原列报版本与更正公告重述日；g0=0 记 none；买入线 1.0454→1.0562、换仓边际 0.15 保留。用户 2026-09-23 裁定口径，2026-09-24 裁定轨道 A 护栏不通过仍依原则采纳（user_ruling.json）。',
            input_files=str(EXP / 'verification.json'), output_file=str(EXP / 'publication.json'),
            operator_or_script='exp_oi200_203_20260923/scan.py', workflow_version=WORKFLOW_VERSION)])
    account = next(r for r in read(ROOT / 'data/processed/portfolio_account_snapshot.csv') if r['as_of'] == SIGNAL)
    subprocess.run([sys.executable, str(ROOT / 'scripts/screen_daily_volume_price_signals.py'), '--as-of', SIGNAL,
                    '--review-queue', 'data/interim/a_share_report_update_queue.csv',
                    '--model-bands', 'data/processed/a_share_pool_model_bands_adopted.csv',
                    '--hold-bands', 'data/processed/a_share_pool_model_bands_hold.csv',
                    '--nav', account['net_assets_cny'], '--funds', '0', '--cash', account['cash_cny'] or '0',
                    '--debt', account['margin_debt_cny'], '--workers', '16'], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
