"""决策日志：v4.216 落地行（须在重发扫描之前写入）。"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION  # noqa: E402

ROWS = [
    ('OI-213-20260928', 'mechanism_repair', 'valuation_caliber', 'adopted',
     'OI-213（v4.216）：ROIC 路径研发费用资本化——证监会行业大类定摊销年限（软件与互联网 3 年、医药制造 10 年、其余 5 年），2017 年前与缺报年份按基年研发强度回填；EBIT 加回研发减摊销、投入资本加研发资产、资本开支与折旧摊销同源；只对可得日不早于基年年报的带使用，唯一实现 roic_inputs.capitalize_rd，建带 --rd-capitalize on。机制：研发强度 ≥ 5% 公司 ROIC 两年持续性 0.622→0.630，非正 NOPAT 年份减少；公允性（2018 年起，参考）V 升一侧 λ 2.4～3.0、V 降一侧方向相反；第 13 款近零；回测（线 1.0034）主读数 +0.01／+1.51、复利 +2.57／−1.76。用户 2026-09-28 按机制正确性采纳，买入线按 §12.1 对齐容差重解 1.0495→1.0034（原线合格面 19.698%），当晚落地并重发 09-28 计划。',
     'data/experiments/exp_oi213_20260928/mechanism.md;data/experiments/exp_oi213_20260928/fairness_RD.json'),
]


def main():
    done = {r['run_id'] for r in csv.DictReader(open(DEFAULT_DECISION_LOG, encoding='utf-8'))}
    rows = [dict(logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage=stage, run_id=run_id, as_of='2026-09-28',
                 security_code='ALL', decision_type=kind, decision_result=result, summary_reason=reason, input_files=inputs,
                 output_file='data/experiments/exp_oi213_20260928/publication.json', operator_or_script='exp_oi213_20260928/log.py',
                 workflow_version=WORKFLOW_VERSION)
            for run_id, stage, kind, result, reason, inputs in ROWS if run_id not in done]
    if rows:
        append_decision_log(DEFAULT_DECISION_LOG, rows)
    print('decision log rows appended', len(rows))


if __name__ == '__main__':
    main()
