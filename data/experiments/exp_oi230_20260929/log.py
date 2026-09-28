"""决策日志：v4.221 落地行（须在重发扫描之前写入）。"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION  # noqa: E402

ROWS = [
    ('OI-230-20260929', 'mechanism_repair', 'valuation_caliber', 'adopted',
     'OI-230（v4.221）：银行 DDM 终值期派息率取可持续派息率 1 − g_T ÷ ROE_T（清洁盈余一致，与同一路径剩余收益相等，派息率为 0 也可估），'
     'V_D0 不可得而 V_DDM 可估的银行照用当日截面 G；同尺系数在该口径上重估 k = 0.7045（c = −0.0206、b = −0.0588）。原口径终值按当期派息率而增长封顶 3%，'
     '使银行 V 近似与派息率成正比（截面秩相关 −0.75 → +0.07），平安银行 2010–2020 年 V 仅 0.3～4.4 元。参考读数略偏原口径：银行内排序 3 年 −0.256 → −0.232（差 t 0.2），'
     '银行机会捕捉 12.4% → 3.5%（2021–2023 年高派息银行移出买入区），回测复利 −1.92／−2.21pp（由陕西煤业路径效应决定）。用户 2026-09-29 按清洁盈余原则采纳，当晚落地并重发 09-28 计划；'
     '买入线 1.0034 在对齐容差内保留，在册合格面重登 11.761%，按 DC 臂重登 BASE；派息率的预测力另登记待办。',
     'data/experiments/exp_oi230_20260929/valuation.md;data/experiments/exp_oi230_20260929/calibration.json'),
]


def main():
    done = {r['run_id'] for r in csv.DictReader(open(DEFAULT_DECISION_LOG, encoding='utf-8'))}
    rows = [dict(logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage=stage, run_id=run_id, as_of='2026-09-28',
                 security_code='ALL', decision_type=kind, decision_result=result, summary_reason=reason, input_files=inputs,
                 output_file='data/experiments/exp_oi230_20260929/publication.json', operator_or_script='exp_oi230_20260929/log.py',
                 workflow_version=WORKFLOW_VERSION)
            for run_id, stage, kind, result, reason, inputs in ROWS if run_id not in done]
    if rows:
        append_decision_log(DEFAULT_DECISION_LOG, rows)
    print('decision log rows appended', len(rows))


if __name__ == '__main__':
    main()
