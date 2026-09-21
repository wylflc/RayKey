"""Republish the signal day with the user's recorded account and budget."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from prepare import EXP, ROOT, read, digest
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION


def main():
    for name in ('a_share_holdings.csv','portfolio_account_snapshot.csv'):
        assert digest(ROOT/'data/processed'/name)==digest(EXP/'old_inputs/data/processed'/name), name
    run_id='OI-198-20260921'
    if not any(r['run_id']==run_id for r in read(DEFAULT_DECISION_LOG)):
        append_decision_log(DEFAULT_DECISION_LOG,[dict(logged_at_utc=datetime.now(timezone.utc).isoformat(),
            workflow_stage='mechanism_repair',run_id=run_id,as_of='2026-09-21',security_code='ALL',
            decision_type='historical_state_sync',decision_result='adopted',
            summary_reason='OI-198：少数股东负账面扣减零下界；全存量普查及无尾位例外的旧组复现通过，轨道A护栏通过；保留旧BASE输入。',
            input_files=str(EXP/'verification.json'),output_file=str(EXP/'publication.json'),
            operator_or_script='exp_oi198_20260921/scan.py',workflow_version=WORKFLOW_VERSION)])
    account=next(r for r in read(ROOT/'data/processed/portfolio_account_snapshot.csv') if r['as_of']=='2026-09-21')
    execution=json.loads((ROOT/'data/interim/daily_execution_2026-09-21.json').read_text())
    assert execution['execution_date']=='2026-09-21'
    subprocess.run([sys.executable,str(ROOT/'scripts/screen_daily_volume_price_signals.py'),
        '--as-of','2026-09-21','--review-queue','data/interim/a_share_report_update_queue.csv',
        '--model-bands','data/processed/a_share_pool_model_bands_adopted.csv',
        '--hold-bands','data/processed/a_share_pool_model_bands_hold.csv',
        '--nav',account['net_assets_cny'],'--funds',str(execution['scan_funds_cny']),
        '--cash',account['cash_cny'],'--debt',account['margin_debt_cny'],'--workers','16'],cwd=ROOT,check=True)


if __name__=='__main__':main()
