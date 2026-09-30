"""决策日志：v4.224 落地行（须在重发扫描之前写入）。"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION  # noqa: E402

ROWS = [
    ('OI-244-20260930', 'mechanism_repair', 'valuation_caliber', 'adopted',
     'OI-244（v4.224）：取消银行同尺系数，bank_valuation.BANK_SCALE 0.7045 → 1，银行 V = V_DDM × G（或退回 V_D0）不再缩放，保险本不乘；历史 rebuild_bank_bands.py h2 缺省取它、实盘 bank_live_value 与池外档案同读。'
     '依据（§12.294）：沿用 k = 0.7045 的原始观测按起始月分段，银行偏差 c 为 2010–2013 +2.3、2014–2016 −3.8、2017–2019 −13.2、2020 年起 0.0（k 1.00 [0.77, 1.41]）、2022 年起 +3.0pp，'
     '全期 −2.06 主要来自 2017–2019 起始月，短窗斜率不稳、全部样本 k 仅 0.21；招行全期 +3.9、其余银行 −2.4，2020 年起两者都约 0。独立审视招行绝对 P/V 约 0.8～0.9，与不缩放的模型 0.89 一致。'
     '用户 2026-09-30 裁定 B（取消系数），当晚落地并重发 09-30 计划。买入线维持 1.0034：同尺缩放不做 §12.1 对齐（对齐解 0.8857 会收紧全部非金融），在册合格面按新口径原线合格面重登为 16.916%（原 11.761%），按 K1 臂重登 BASE。'
     '回测参考（§12.295）：K1 对现行主读数 −0.24／−1.12（全／A），复利 −3.84／−4.29pp，0/14 起点，最大回撤中位不变。',
     'data/experiments/exp_oi244_20260930/readings.md;data/experiments/exp_land_v4224_20260930/readings.md;data/experiments/exp_land_v4224_20260930/build_check.json;data/experiments/exp_land_v4224_20260930/align.txt'),
]


def main():
    done = {r['run_id'] for r in csv.DictReader(open(DEFAULT_DECISION_LOG, encoding='utf-8'))}
    rows = [dict(logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage=stage, run_id=run_id, as_of='2026-09-30',
                 security_code='ALL', decision_type=kind, decision_result=result, summary_reason=reason, input_files=inputs,
                 output_file='data/experiments/exp_land_v4224_20260930/publication.json', operator_or_script='exp_land_v4224_20260930/log.py',
                 workflow_version=WORKFLOW_VERSION)
            for run_id, stage, kind, result, reason, inputs in ROWS if run_id not in done]
    if rows:
        append_decision_log(DEFAULT_DECISION_LOG, rows)
    print('decision log rows appended', len(rows))


if __name__ == '__main__':
    main()
