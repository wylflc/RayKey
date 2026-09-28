"""决策日志：v4.219 落地行（须在重发扫描之前写入）。"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION  # noqa: E402

ROWS = [
    ('OI-227-20260928', 'mechanism_repair', 'valuation_caliber', 'adopted',
     'OI-227（v4.219）：银行 V（含退回的股利利差）乘同尺系数 k = 0.6951，保险不乘；唯一常数 bank_valuation.BANK_SCALE，历史 rebuild_bank_bands.py h2 缺省取它、实盘 bank_live_value 与池外档案同读。'
     '同尺校准：面板月末 P/V 对 3 年年化回报月效应回归，共同斜率 b = −0.0565、银行偏差 c = −0.0205 [−0.0376, −0.0025]（v4.216 口径），k = exp(−c/b)。统一线下银行买入区机会 1.95 倍基准、陷阱 0.9%；'
     '单独银行线 0.677 的回测主读数 −2.04／+3.58、陷阱段贡献 −10.5pp。用户 2026-09-28 按正确性原则采纳（避免银行系统性低估或高估，陷阱另行识别，不为回测改原则），选同尺校准全期、缩放银行 V、当晚落地并重发 09-28 计划。买入线维持 1.0034：银行同尺缩放不做 §12.1 对齐（对齐解 1.1568 会放宽全部非金融），在册合格面按新口径原线合格面重登为 11.689%（原 17.777%），按 BK 臂重登 BASE。',
     'data/experiments/exp_oi227_20260928/recalibration_v4216.json;data/experiments/exp_oi227_20260928/bank_zone.md'),
]


def main():
    done = {r['run_id'] for r in csv.DictReader(open(DEFAULT_DECISION_LOG, encoding='utf-8'))}
    rows = [dict(logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage=stage, run_id=run_id, as_of='2026-09-28',
                 security_code='ALL', decision_type=kind, decision_result=result, summary_reason=reason, input_files=inputs,
                 output_file='data/experiments/exp_land_v4219_20260928/publication.json', operator_or_script='exp_land_v4219_20260928/log.py',
                 workflow_version=WORKFLOW_VERSION)
            for run_id, stage, kind, result, reason, inputs in ROWS if run_id not in done]
    if rows:
        append_decision_log(DEFAULT_DECISION_LOG, rows)
    print('decision log rows appended', len(rows))


if __name__ == '__main__':
    main()
