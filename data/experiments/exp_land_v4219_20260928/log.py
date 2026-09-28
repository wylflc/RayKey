"""决策日志：v4.215 落地行（须在重发扫描之前写入）。"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION  # noqa: E402

ROWS = [
    ('OI-207-20260928', 'mechanism_repair', 'valuation_caliber', 'adopted',
     'OI-207（v4.215）：银行估值改为股利尺度 × DDM 排序——V = V_DDM × G，G 为当日两者都可估的银行 V_D0 ÷ V_DDM 的几何均值（不足 5 只或该行不可估退回 V_D0），保险仍按股利利差；唯一实现 bank_valuation，历史 rebuild_bank_bands.py h2:0.02:0.10、实盘与池外档案同源。九法检验：银行内 3 年排序 −0.26（现行 −0.17，1 年显著），银行陷阱占比 1.59→0.81 倍；统一买入线下机会提升 2.09→1.72，回测复利 −4.68pp（0/14）、去赢家主读数 −16.9pp。用户 2026-09-28 按估值准确性采纳（买入线不必统一，银行可与非金融分开判定，另登记 OI-227）；原线 1.0670 合格面 18.393% 超出 §12.1 容差，用户裁定重解买入线为 1.0495（17.777%），当晚落地并重发 09-28 计划。',
     'data/experiments/exp_oi207_h2_20260928/case_attribution.md;data/experiments/exp_oi207_20260928/hybrids.json'),
]


def main():
    done = {r['run_id'] for r in csv.DictReader(open(DEFAULT_DECISION_LOG, encoding='utf-8'))}
    rows = [dict(logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage=stage, run_id=run_id, as_of='2026-09-28',
                 security_code='ALL', decision_type=kind, decision_result=result, summary_reason=reason, input_files=inputs,
                 output_file='data/experiments/exp_land_v4215_20260928/publication.json', operator_or_script='exp_land_v4215_20260928/log.py',
                 workflow_version=WORKFLOW_VERSION)
            for run_id, stage, kind, result, reason, inputs in ROWS if run_id not in done]
    if rows:
        append_decision_log(DEFAULT_DECISION_LOG, rows)
    print('decision log rows appended', len(rows))


if __name__ == '__main__':
    main()
